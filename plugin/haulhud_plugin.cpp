/**
 * HaulHUD telemetry plugin for ETS2/ATS.
 *
 * Reads job, navigation and truck telemetry via the SCS Telemetry SDK and
 * publishes it into a memory-mapped file (Local\HaulHUDSharedMemory)
 * for the HaulHUD Python application to read.
 *
 * This DLL intentionally contains NO UI/rendering logic. It must stay small
 * and crash-proof since it runs inside the game process. All formatting,
 * unit conversion and display logic lives in the separate overlay app.
 *
 * See ../SHARED_MEMORY_LAYOUT.md for the exact struct contract.
 */

#ifdef _WIN32
#  define WINVER 0x0600
#  define _WIN32_WINNT 0x0600
#  include <windows.h>
#endif

#include <cstdio>
#include <cstring>
#include <cstdlib>

#include "scssdk_telemetry.h"
#include "eurotrucks2/scssdk_eut2.h"
#include "eurotrucks2/scssdk_telemetry_eut2.h"
#include "common/scssdk_telemetry_common_channels.h"
#include "common/scssdk_telemetry_common_configs.h"
#include "common/scssdk_telemetry_job_common_channels.h"
#include "common/scssdk_telemetry_truck_common_channels.h"

#define UNUSED(x)

// ---------------------------------------------------------------------
// Shared memory struct. Must exactly match SHARED_MEMORY_LAYOUT.md and
// the Python-side struct.unpack format string. #pragma pack(1) so the
// compiler inserts no padding we didn't account for by hand.
// ---------------------------------------------------------------------
#pragma pack(push, 1)
struct SharedState
{
	scs_u32_t schema_version;      // offset 0
	scs_u32_t seq;                  // offset 4  (sequence lock)
	scs_u8_t  game_connected;       // offset 8
	scs_u8_t  game_paused;          // offset 9
	scs_u8_t  job_active;           // offset 10
	scs_u8_t  _pad0;                // offset 11

	float     local_scale;          // offset 12
	scs_u32_t game_time_minutes;    // offset 16
	scs_u32_t delivery_time_minutes;// offset 20
	scs_s32_t rest_stop_minutes;    // offset 24

	float     nav_distance_m;       // offset 28
	float     nav_time_s;           // offset 32
	float     nav_speed_limit_ms;   // offset 36

	scs_u32_t planned_distance_km;  // offset 40
	float     truck_speed_ms;       // offset 44
	float     cargo_damage_pct;     // offset 48
	float     cargo_mass_kg;        // offset 52

	char      cargo_name[64];       // offset 56
	char      source_city[64];      // offset 120
	char      destination_city[64]; // offset 184
	char      source_company[64];   // offset 248
	char      destination_company[64]; // offset 312
	char      job_market[32];       // offset 376

	scs_u64_t income;               // offset 408
	scs_u8_t  is_special_job;       // offset 416
	scs_u8_t  _pad1[7];             // offset 417
};
#pragma pack(pop)

static const scs_u32_t SCHEMA_VERSION = 1;
static const wchar_t* SHM_NAME = L"Local\\HaulHUDSharedMemory";

// ---------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------

static HANDLE g_map_handle = NULL;
static SharedState* g_shm = NULL;

// Local mirror of everything we track. We only push this into shared
// memory at frame_end so we always publish a complete, consistent frame.
struct LocalState
{
	bool  game_paused;
	bool  job_active;

	float local_scale;
	scs_u32_t game_time_minutes;
	scs_u32_t delivery_time_minutes;
	scs_s32_t rest_stop_minutes;

	float nav_distance_m;
	float nav_time_s;
	float nav_speed_limit_ms;

	scs_u32_t planned_distance_km;
	float truck_speed_ms;
	float cargo_damage_pct;
	float cargo_mass_kg;

	char cargo_name[64];
	char source_city[64];
	char destination_city[64];
	char source_company[64];
	char destination_company[64];
	char job_market[32];

	scs_u64_t income;
	bool is_special_job;
} g_state;

static scs_log_t game_log = NULL;

static void log_msg(const scs_log_type_t type, const char* text)
{
	if (game_log) {
		game_log(type, text);
	}
}

// ---------------------------------------------------------------------
// Shared memory setup / teardown
// ---------------------------------------------------------------------

static bool init_shared_memory(void)
{
#ifdef _WIN32
	g_map_handle = CreateFileMappingW(
		INVALID_HANDLE_VALUE,
		NULL,
		PAGE_READWRITE,
		0,
		sizeof(SharedState),
		SHM_NAME
	);
	if (!g_map_handle) {
		return false;
	}

	g_shm = static_cast<SharedState*>(MapViewOfFile(
		g_map_handle,
		FILE_MAP_ALL_ACCESS,
		0, 0,
		sizeof(SharedState)
	));
	if (!g_shm) {
		CloseHandle(g_map_handle);
		g_map_handle = NULL;
		return false;
	}

	memset(g_shm, 0, sizeof(SharedState));
	g_shm->schema_version = SCHEMA_VERSION;
	return true;
#else
	return false;
#endif
}

static void shutdown_shared_memory(void)
{
#ifdef _WIN32
	if (g_shm) {
		// Mark disconnected so the overlay shows "not running" instead of
		// stale frozen numbers.
		g_shm->game_connected = 0;
		UnmapViewOfFile(g_shm);
		g_shm = NULL;
	}
	if (g_map_handle) {
		CloseHandle(g_map_handle);
		g_map_handle = NULL;
	}
#endif
}

// Copies the local state into shared memory using a sequence-lock so the
// Python reader can detect (and retry past) a torn read without needing a
// real cross-process mutex.
static void publish_state(void)
{
	if (!g_shm) {
		return;
	}

	g_shm->seq++; // odd => write in progress

	g_shm->game_connected = 1;
	g_shm->game_paused = g_state.game_paused ? 1 : 0;
	g_shm->job_active = g_state.job_active ? 1 : 0;

	g_shm->local_scale = g_state.local_scale;
	g_shm->game_time_minutes = g_state.game_time_minutes;
	g_shm->delivery_time_minutes = g_state.delivery_time_minutes;
	g_shm->rest_stop_minutes = g_state.rest_stop_minutes;

	g_shm->nav_distance_m = g_state.nav_distance_m;
	g_shm->nav_time_s = g_state.nav_time_s;
	g_shm->nav_speed_limit_ms = g_state.nav_speed_limit_ms;

	g_shm->planned_distance_km = g_state.planned_distance_km;
	g_shm->truck_speed_ms = g_state.truck_speed_ms;
	g_shm->cargo_damage_pct = g_state.cargo_damage_pct;
	g_shm->cargo_mass_kg = g_state.cargo_mass_kg;

	memcpy(g_shm->cargo_name, g_state.cargo_name, sizeof(g_shm->cargo_name));
	memcpy(g_shm->source_city, g_state.source_city, sizeof(g_shm->source_city));
	memcpy(g_shm->destination_city, g_state.destination_city, sizeof(g_shm->destination_city));
	memcpy(g_shm->source_company, g_state.source_company, sizeof(g_shm->source_company));
	memcpy(g_shm->destination_company, g_state.destination_company, sizeof(g_shm->destination_company));
	memcpy(g_shm->job_market, g_state.job_market, sizeof(g_shm->job_market));

	g_shm->income = g_state.income;
	g_shm->is_special_job = g_state.is_special_job ? 1 : 0;

	g_shm->seq++; // even => write complete
}

// ---------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------

static void copy_string_field(char* dest, size_t dest_size, const char* src)
{
	if (!src) {
		memset(dest, 0, dest_size);
		return;
	}
	strncpy(dest, src, dest_size - 1);
	dest[dest_size - 1] = '\0';
	// zero-fill remainder so stale bytes never leak into the field
	size_t used = strlen(dest);
	if (used + 1 < dest_size) {
		memset(dest + used + 1, 0, dest_size - used - 1);
	}
}

// ---------------------------------------------------------------------
// Channel callbacks
// ---------------------------------------------------------------------

SCSAPI_VOID cb_store_float(const scs_string_t UNUSED(name), const scs_u32_t UNUSED(index), const scs_value_t* const value, const scs_context_t context)
{
	if (!value || !context) return;
	*static_cast<float*>(context) = value->value_float.value;
}

SCSAPI_VOID cb_store_u32(const scs_string_t UNUSED(name), const scs_u32_t UNUSED(index), const scs_value_t* const value, const scs_context_t context)
{
	if (!value || !context) return;
	*static_cast<scs_u32_t*>(context) = value->value_u32.value;
}

SCSAPI_VOID cb_store_s32(const scs_string_t UNUSED(name), const scs_u32_t UNUSED(index), const scs_value_t* const value, const scs_context_t context)
{
	if (!value || !context) return;
	*static_cast<scs_s32_t*>(context) = value->value_s32.value;
}

// rest.stop / navigation channels can go "no value" (e.g. no route set,
// fatigue sim disabled). Register these WITH the no_value flag and reset
// to a sentinel when value is NULL so the overlay can show "N/A" instead
// of a stale or zeroed number.

SCSAPI_VOID cb_store_s32_or_reset(const scs_string_t UNUSED(name), const scs_u32_t UNUSED(index), const scs_value_t* const value, const scs_context_t context)
{
	if (!context) return;
	if (!value) {
		*static_cast<scs_s32_t*>(context) = -1; // sentinel: unavailable
		return;
	}
	*static_cast<scs_s32_t*>(context) = value->value_s32.value;
}

SCSAPI_VOID cb_store_float_or_reset(const scs_string_t UNUSED(name), const scs_u32_t UNUSED(index), const scs_value_t* const value, const scs_context_t context)
{
	if (!context) return;
	if (!value) {
		*static_cast<float*>(context) = -1.0f; // sentinel: unavailable
		return;
	}
	*static_cast<float*>(context) = value->value_float.value;
}

// ---------------------------------------------------------------------
// Event callbacks
// ---------------------------------------------------------------------

SCSAPI_VOID on_frame_end(const scs_event_t UNUSED(event), const void* const UNUSED(event_info), const scs_context_t UNUSED(context))
{
	publish_state();
}

SCSAPI_VOID on_pause(const scs_event_t event, const void* const UNUSED(event_info), const scs_context_t UNUSED(context))
{
	g_state.game_paused = (event == SCS_TELEMETRY_EVENT_paused);
}

// Reads a named string attribute out of a configuration attribute array.
// Returns NULL if not present.
static const char* find_string_attribute(const scs_named_value_t* attributes, const char* name)
{
	for (const scs_named_value_t* cur = attributes; cur->name; ++cur) {
		if (strcmp(cur->name, name) == 0 && cur->value.type == SCS_VALUE_TYPE_string) {
			return cur->value.value_string.value;
		}
	}
	return NULL;
}

static const scs_named_value_t* find_attribute(const scs_named_value_t* attributes, const char* name)
{
	for (const scs_named_value_t* cur = attributes; cur->name; ++cur) {
		if (strcmp(cur->name, name) == 0) {
			return cur;
		}
	}
	return NULL;
}

SCSAPI_VOID on_configuration(const scs_event_t UNUSED(event), const void* const event_info, const scs_context_t UNUSED(context))
{
	const scs_telemetry_configuration_t* const info = static_cast<const scs_telemetry_configuration_t*>(event_info);
	if (!info || !info->id) {
		return;
	}

	if (strcmp(info->id, SCS_TELEMETRY_CONFIG_job) != 0) {
		return; // we only care about the job config here
	}

	// Empty attribute set means no active job.
	if (!info->attributes || !info->attributes->name) {
		g_state.job_active = false;
		memset(g_state.cargo_name, 0, sizeof(g_state.cargo_name));
		memset(g_state.destination_city, 0, sizeof(g_state.destination_city));
		memset(g_state.destination_company, 0, sizeof(g_state.destination_company));
		memset(g_state.source_city, 0, sizeof(g_state.source_city));
		memset(g_state.source_company, 0, sizeof(g_state.source_company));
		memset(g_state.job_market, 0, sizeof(g_state.job_market));
		g_state.delivery_time_minutes = 0;
		g_state.planned_distance_km = 0;
		g_state.income = 0;
		g_state.is_special_job = false;
		return;
	}

	g_state.job_active = true;

	copy_string_field(g_state.cargo_name, sizeof(g_state.cargo_name),
		find_string_attribute(info->attributes, SCS_TELEMETRY_CONFIG_ATTRIBUTE_cargo));
	copy_string_field(g_state.source_city, sizeof(g_state.source_city),
		find_string_attribute(info->attributes, SCS_TELEMETRY_CONFIG_ATTRIBUTE_source_city));
	copy_string_field(g_state.destination_city, sizeof(g_state.destination_city),
		find_string_attribute(info->attributes, SCS_TELEMETRY_CONFIG_ATTRIBUTE_destination_city));
	copy_string_field(g_state.source_company, sizeof(g_state.source_company),
		find_string_attribute(info->attributes, SCS_TELEMETRY_CONFIG_ATTRIBUTE_source_company));
	copy_string_field(g_state.destination_company, sizeof(g_state.destination_company),
		find_string_attribute(info->attributes, SCS_TELEMETRY_CONFIG_ATTRIBUTE_destination_company));
	copy_string_field(g_state.job_market, sizeof(g_state.job_market),
		find_string_attribute(info->attributes, SCS_TELEMETRY_CONFIG_ATTRIBUTE_job_market));

	if (const scs_named_value_t* v = find_attribute(info->attributes, SCS_TELEMETRY_CONFIG_ATTRIBUTE_delivery_time)) {
		if (v->value.type == SCS_VALUE_TYPE_u32) g_state.delivery_time_minutes = v->value.value_u32.value;
	}
	if (const scs_named_value_t* v = find_attribute(info->attributes, SCS_TELEMETRY_CONFIG_ATTRIBUTE_planned_distance_km)) {
		if (v->value.type == SCS_VALUE_TYPE_u32) g_state.planned_distance_km = v->value.value_u32.value;
	}
	if (const scs_named_value_t* v = find_attribute(info->attributes, SCS_TELEMETRY_CONFIG_ATTRIBUTE_cargo_mass)) {
		if (v->value.type == SCS_VALUE_TYPE_float) g_state.cargo_mass_kg = v->value.value_float.value;
	}
	if (const scs_named_value_t* v = find_attribute(info->attributes, SCS_TELEMETRY_CONFIG_ATTRIBUTE_income)) {
		if (v->value.type == SCS_VALUE_TYPE_u64) g_state.income = v->value.value_u64.value;
	}
	if (const scs_named_value_t* v = find_attribute(info->attributes, SCS_TELEMETRY_CONFIG_ATTRIBUTE_special_job)) {
		if (v->value.type == SCS_VALUE_TYPE_bool) g_state.is_special_job = (v->value.value_bool.value != 0);
	}
}

// ---------------------------------------------------------------------
// Init / shutdown
// ---------------------------------------------------------------------

SCSAPI_RESULT scs_telemetry_init(const scs_u32_t version, const scs_telemetry_init_params_t* const params)
{
	if (version != SCS_TELEMETRY_VERSION_1_01) {
		return SCS_RESULT_unsupported;
	}

	const scs_telemetry_init_params_v101_t* const p =
		static_cast<const scs_telemetry_init_params_v101_t*>(params);

	game_log = p->common.log;

	if (strcmp(p->common.game_id, SCS_GAME_ID_EUT2) != 0) {
		// This build targets ETS2. Fail cleanly for other games rather than
		// silently reporting wrong units/scale.
		log_msg(SCS_LOG_TYPE_warning, "[HaulHUD] Non-ETS2 game detected; plugin will still attempt to run.");
	}

	memset(&g_state, 0, sizeof(g_state));
	g_state.local_scale = 19.0f; // sane default until local.scale channel reports in

	if (!init_shared_memory()) {
		log_msg(SCS_LOG_TYPE_error, "[HaulHUD] Failed to create shared memory mapping.");
		return SCS_RESULT_generic_error;
	}

	const bool events_ok =
		(p->register_for_event(SCS_TELEMETRY_EVENT_frame_end, on_frame_end, NULL) == SCS_RESULT_ok) &&
		(p->register_for_event(SCS_TELEMETRY_EVENT_paused, on_pause, NULL) == SCS_RESULT_ok) &&
		(p->register_for_event(SCS_TELEMETRY_EVENT_started, on_pause, NULL) == SCS_RESULT_ok);

	if (!events_ok) {
		log_msg(SCS_LOG_TYPE_error, "[HaulHUD] Failed to register core events.");
		shutdown_shared_memory();
		return SCS_RESULT_generic_error;
	}

	p->register_for_event(SCS_TELEMETRY_EVENT_configuration, on_configuration, NULL);

	// Time / rest channels (scssdk_telemetry_common_channels.h)
	p->register_for_channel(SCS_TELEMETRY_CHANNEL_local_scale, SCS_U32_NIL, SCS_VALUE_TYPE_float, SCS_TELEMETRY_CHANNEL_FLAG_none, cb_store_float, &g_state.local_scale);
	p->register_for_channel(SCS_TELEMETRY_CHANNEL_game_time, SCS_U32_NIL, SCS_VALUE_TYPE_u32, SCS_TELEMETRY_CHANNEL_FLAG_none, cb_store_u32, &g_state.game_time_minutes);
	p->register_for_channel(SCS_TELEMETRY_CHANNEL_next_rest_stop, SCS_U32_NIL, SCS_VALUE_TYPE_s32, SCS_TELEMETRY_CHANNEL_FLAG_no_value, cb_store_s32_or_reset, &g_state.rest_stop_minutes);

	// Navigation channels (scssdk_telemetry_truck_common_channels.h)
	p->register_for_channel(SCS_TELEMETRY_TRUCK_CHANNEL_navigation_distance, SCS_U32_NIL, SCS_VALUE_TYPE_float, SCS_TELEMETRY_CHANNEL_FLAG_no_value, cb_store_float_or_reset, &g_state.nav_distance_m);
	p->register_for_channel(SCS_TELEMETRY_TRUCK_CHANNEL_navigation_time, SCS_U32_NIL, SCS_VALUE_TYPE_float, SCS_TELEMETRY_CHANNEL_FLAG_no_value, cb_store_float_or_reset, &g_state.nav_time_s);
	p->register_for_channel(SCS_TELEMETRY_TRUCK_CHANNEL_navigation_speed_limit, SCS_U32_NIL, SCS_VALUE_TYPE_float, SCS_TELEMETRY_CHANNEL_FLAG_no_value, cb_store_float_or_reset, &g_state.nav_speed_limit_ms);

	// Truck speed
	p->register_for_channel(SCS_TELEMETRY_TRUCK_CHANNEL_speed, SCS_U32_NIL, SCS_VALUE_TYPE_float, SCS_TELEMETRY_CHANNEL_FLAG_none, cb_store_float, &g_state.truck_speed_ms);

	// Cargo damage (job channel)
	p->register_for_channel(SCS_TELEMETRY_JOB_CHANNEL_cargo_damage, SCS_U32_NIL, SCS_VALUE_TYPE_float, SCS_TELEMETRY_CHANNEL_FLAG_none, cb_store_float, &g_state.cargo_damage_pct);

	log_msg(SCS_LOG_TYPE_message, "[HaulHUD] Plugin initialized.");
	return SCS_RESULT_ok;
}

SCSAPI_VOID scs_telemetry_shutdown(void)
{
	log_msg(SCS_LOG_TYPE_message, "[HaulHUD] Plugin shutting down.");
	shutdown_shared_memory();
	game_log = NULL;
}

#ifdef _WIN32
BOOL APIENTRY DllMain(HMODULE UNUSED(module), DWORD reason_for_call, LPVOID UNUSED(reserved))
{
	if (reason_for_call == DLL_PROCESS_DETACH) {
		shutdown_shared_memory();
	}
	return TRUE;
}
#endif
