# Microsoft Copilot Studio Integration

> **Note:** This is **Microsoft Copilot Studio** (Power Platform connector topics), not **GitHub Copilot** CLI or cloud agent. For GitHub Copilot shell hooks, see [adapters/github_copilot/README.md](../github_copilot/README.md).

Copilot does not use local shell hooks. FireGuard runs inside **Power Platform custom connector** topics.

## Prerequisites

1. Import the Fireraven FireGuard custom connector in Copilot Studio.
2. Configure `project_id` and API key on the connector connection.
3. Import the topic YAML files in `topics/`.

## Topics

| File | Purpose |
|------|---------|
| `topics/01_input_guardrail.yaml` | Create/reuse conversation, run input guardrails, block unsafe prompts |
| `topics/02_output_guardrail.yaml` | Run output guardrails using stored `input_id` (audit/block in flow) |

## Flow overview

```
User message
  → createConversationCopilot (conversation_copilot_id = System.Conversation.Id)
  → inputGuardrails (messages_history)
  → if not is_safe → block and cancel dialog
  → else → continue to LLM
  → outputGuardrails (input_id + assistant output)
```

See [Fireraven Copilot connector assets](https://github.com/fireravenai/fireraven-app/tree/main/src/assets/connectors/copilot) for the official connector OpenAPI definition.
