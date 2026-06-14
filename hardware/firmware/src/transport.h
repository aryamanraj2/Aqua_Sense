#pragma once
/**
 * transport.h — Transport: HTTP/JSON cognition-tier communication
 *
 * Abstracts all network IO so the transport can be swapped to MQTT without
 * touching application logic (main.cpp, safety.cpp know nothing about HTTP).
 *
 * All methods are synchronous with HTTP_TIMEOUT_MS timeout.
 * Failures are logged; the caller decides whether to retry.
 */

#include "sensors.h"
#include "safety.h"
#include "actuators.h"
#include <stdint.h>

// Maximum commands returned per poll (avoids stack overflow on large queues)
static constexpr uint8_t MAX_COMMANDS_PER_POLL = 8;

struct CommandList {
    Command items[MAX_COMMANDS_PER_POLL];
    uint8_t count = 0;
};

class Transport {
public:
    void begin(const char* nodeId, const char* backendUrl);

    bool registerNode(const char* fwVersion,
                      const char* hwRevision,
                      const NodeCapabilities& caps);

    bool postHeartbeat(const char* fwVersion,
                       const InterlockState& interlocks);

    bool postTelemetry(const SensorReading& reading,
                       const InterlockState& interlocks);

    CommandList pollCommands();

    bool postAck(const char* commandId, const AckStatus& ack);

private:
    char _nodeId[32]     = {};
    char _baseUrl[128]   = {};

    // Returns HTTP status code; body written into buf (null-terminated)
    int  _post(const char* path, const char* body, char* respBuf, size_t respLen);
    int  _get (const char* path, char* respBuf, size_t respLen);

    void _buildNodeUrl(char* out, size_t len, const char* suffix) const;
};
