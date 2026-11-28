# deps.dev

Uses the public [v3 API](https://docs.deps.dev/api/v3/) without credentials.
Package/version metadata covers Cargo, Go, Maven, npm, NuGet, PyPI and RubyGems.
Resolved dependency graphs currently cover Cargo, Maven, npm and PyPI.

The provider has [no formally specified rate limit](https://github.com/google/deps.dev/issues/33#issuecomment-1744108819).
The adapter's 60 requests/minute is a conservative client limit, not a provider quota.
The shared HTTP client supplies bounded exponential backoff on 429 and transient errors.

Responses and recorded cassettes originate from **Google Open Source Insights (deps.dev)**.
[Generated dependency data is CC BY 4.0](https://docs.deps.dev/api/v3/#data), with its
[license](https://creativecommons.org/licenses/by/4.0/) included in graph results.
Aggregated package metadata retains its upstream sources' terms. API access follows the
[Google API Terms](https://developers.google.com/terms); deps.dev explicitly permits caching.
The adapter selects fields and caps lists; recorded responses retain the upstream bodies
except the shared recorder's email redactions. Every result includes its source URL.

Recent versions sort by publication date, not version-string ordering. Default versions
are returned separately if outside the requested recent list. Dependency nodes preserve
provider order (root first); edges reference only returned node indexes. Truncation and
provider graph/node errors are reported independently so a capped or failed resolution
cannot be mistaken for a complete dependency graph.
