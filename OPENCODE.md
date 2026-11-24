# OpenCode with Huawei Cloud MaaS

From this directory, start OpenCode:

```bash
opencode
```

`opencode.json` reads the API key from the private, Git-ignored `.maas-api-key`
file, so no shell exports are required. The file has owner-only permissions.
After changing `MAAS_API_KEY` in `.env`, run `./opencode-maas` once to refresh
the key file and start OpenCode. Store the raw API key without a `Bearer` prefix;
the adapter adds the prefix automatically.

`opencode.json` selects
`huawei-maas/glm-5.3` as the default model and uses the OpenAI-compatible chat
adapter. The API key is not copied into the configuration.

The base URL is the existing `.env` endpoint with `/chat/completions` removed:
`https://api-ap-southeast-1.modelarts-maas.com/v2`. The adapter appends that
path itself. The model includes reasoning-content support for tool calls.

To list the configured model or run a quick connection check:

```bash
opencode models huawei-maas
opencode run 'Reply with exactly MAAS_OK. Do not use tools.'
```

You can also select **Huawei Cloud MaaS / GLM-5.3** using `/models` in OpenCode.
If you change the model or endpoint in `.env`, update `opencode.json` to match.

Configuration parsing and model discovery were verified with `MAAS_API_KEY`
unset in the shell. A live request could not be verified because this
environment could not resolve the Huawei API hostname.
