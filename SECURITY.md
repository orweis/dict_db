# Security policy

## Supported versions

Only the latest release (currently 2.x) receives security fixes. 1.x is Python 2
only and unsupported.

## Reporting a vulnerability

Please report vulnerabilities privately with GitHub's
"Report a vulnerability" button on the repository's **Security** tab (private
vulnerability reporting), not in a public issue. Include the affected version,
a description and, if possible, a minimal reproduction.

## Security model

- `dict_db` trusts the databases it talks to. Anyone who can write to the Redis
  keys or Elasticsearch indices used by your application can change the data
  your application reads.
- The `Pickle*` classes deserialize with `pickle`, so write access to their
  Redis keys or pub/sub channels means **arbitrary code execution** in readers.
  Only use them with a private, authenticated Redis; prefer the `JSON*` classes.
- `QueueApi` calls handler methods requested by anyone who can publish to its
  channels. Handlers must validate their arguments.
- Configure Redis and Elasticsearch with authentication and TLS. Pass
  credentials via the client objects or the `DICT_DB_REDIS_URL` /
  `DICT_DB_ELASTIC_URL` environment variables; never commit them.
