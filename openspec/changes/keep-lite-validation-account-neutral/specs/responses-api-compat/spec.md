## ADDED Requirements

### Requirement: Responses Lite parallel validation is account-neutral

A Responses streaming rejection with code `unsupported_value` and the exact
message "X-OpenAI-Internal-Codex-Responses-Lite requires `parallel_tool_calls`
to be false." MUST NOT increment selected-account error health when its HTTP
status is 400 or absent. Other status codes and unrelated messages MUST retain
the existing account-health classification. The service MUST preserve original
code, message, type, and parameter through the route's existing HTTP or terminal
SSE policy and MUST NOT add replay or change ownership for this rejection.

#### Scenario: Pretty HTTP validation rejection

- **WHEN** a real upstream HTTP 400 carries the exact Lite validation error in a chunked pretty JSON body
- **THEN** the selected account receives no transient error penalty
- **AND** the original structured validation error reaches the public route without waiting for a request timeout

#### Scenario: Unrelated failure is not exempt

- **WHEN** the code or message differs or an explicit HTTP status is not 400
- **THEN** this Lite-specific exemption does not apply

#### Scenario: Native route composition

- **WHEN** a Lite request asks for parallel tools and a loopback upstream independently sends the pretty validation terminal
- **THEN** native HTTP, HTTP bridge, and public Responses paths retain the normalized Lite request and one finite terminal through their established commitment policy
