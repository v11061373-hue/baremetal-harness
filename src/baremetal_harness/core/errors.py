class BareMetalHarnessError(Exception):
    code = "baremetal_harness_error"
    retryable = False
    side_effects_possible = False


class ApplicationConfigurationError(BareMetalHarnessError):
    code = "application_configuration_error"


class ModelError(BareMetalHarnessError):
    code = "model_error"


class AuthenticationError(ModelError):
    code = "model_authentication_error"


class RateLimitError(ModelError):
    code = "model_rate_limit"
    retryable = True


class ModelProtocolError(ModelError):
    code = "model_protocol_error"


class ModelUnavailableError(ModelError):
    code = "model_unavailable"
    retryable = True


class InvariantViolation(BareMetalHarnessError):
    code = "run_invariant_violation"


class ToolError(BareMetalHarnessError):
    code = "tool_error"


class ToolNotFound(ToolError):
    code = "tool_not_found"


class ToolArgumentsInvalid(ToolError):
    code = "tool_arguments_invalid"


class ToolSchemaError(ToolError):
    code = "tool_schema_error"
