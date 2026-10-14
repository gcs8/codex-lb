# Evidence and scope

`POST /v1/images/generations` and `POST /v1/images/edits` currently translate
valid requests into an internal Responses request hosted by `gpt-5.6-luna`.
The source PR reports HTTP 400 with `Tool choice 'image_generation' not
found in 'tools' parameter` and success for the equivalent Responses request
hosted by `gpt-5.6-sol`. Fork preparation verifies only synthetic upstream
fixtures, not current upstream availability or account entitlement.

The change separates Images host selection from default account probes. It does
not change the public image model, multipart-to-`input_image` conversion,
account selection, usage settlement, transport choice, or retry policy.

## Fork preparation

Ported the scoped image commit `76a8391928e2a3627a1cd088099903767bf09c53`
from packet source `0a3156fa7b2a1a3a411280c8caa19609be2af63a` onto
`09de19be6d5065438c6b04689093ee9467abe1a8`. The source also contains an
unrelated 256 MiB Responses ingress-budget change and archived whitespace
cleanup. Neither is included. Current canonical requirements retain existing
authentication, routing, multipart, settlement, and envelope contracts while
updating only the internal image-host order. No new setting is added.

For example, when Sol is visible but suppressed and Astra is visible without
suppression, image requests use Astra. If no candidate qualifies, Sol remains
the fallback and existing account entitlement and downstream errors apply.
This resolver does not retry across hosts or bypass trusted-access policy.
