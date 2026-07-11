This folder needs a few more UNMODIFIED files copied straight from your
SDK's `include/` folder (I don't have their exact contents, so don't
let me — or anyone — hand-type these; copy them verbatim from the SDK zip):

Copy these from SDK include/ root:
  scssdk.h
  scssdk_telemetry_event.h
  scssdk_telemetry_channel.h

Copy from SDK include/common/:
  scssdk_telemetry_common_gameplay_events.h
  scssdk_telemetry_trailer_common_channels.h

Copy from SDK include/eurotrucks2/:
  scssdk_eut2.h

Once copied, the folder structure should look like:

include/
  scssdk.h
  scssdk_telemetry.h
  scssdk_value.h
  scssdk_telemetry_event.h
  scssdk_telemetry_channel.h
  common/
    scssdk_telemetry_common_channels.h
    scssdk_telemetry_common_configs.h
    scssdk_telemetry_common_gameplay_events.h
    scssdk_telemetry_job_common_channels.h
    scssdk_telemetry_truck_common_channels.h
    scssdk_telemetry_trailer_common_channels.h
  eurotrucks2/
    scssdk_eut2.h
    scssdk_telemetry_eut2.h

Delete this README once done.
