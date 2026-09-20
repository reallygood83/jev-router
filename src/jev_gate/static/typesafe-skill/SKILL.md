---
name: typesafe-ai
description: Call TypeSafe Jev for structured decisions (noul/choice/score). Use for Jev, TypeSafe, System One, classification, routing, scoring, yes/no judgments, or guardrails. Not a chat model.
---

# TypeSafe (Jev)

Jev does not chat, summarize, or generate text. Send `state` + typed `questions`; get values code can branch on.

Endpoint: `POST https://api.typesafe.ai/v1/systemone`  
Model: `jev-latest`  
Auth: `Authorization: Bearer $TYPESAFE_API_KEY`

Never print the API key, `.env`, or Authorization header.

```json
{
  "model": "jev-latest",
  "state": { "task": "..." },
  "questions": {
    "urgency": {
      "type": "noul",
      "instructions": "Does this message express urgency?"
    }
  }
}
```

| Type | Ask | Returns |
| --- | --- | --- |
| `noul` | Is this true? | `noul` 0–1. ~0.5 means uncertain |
| `choice` | Which option? | `choice`, `probabilities`, `confidence` |
| `score` | Where on this rubric? | `score`, `legend`, `probabilities`, `confidence` |

Rules: one snap judgment per question; put the full question in `instructions`; include `other` when the list might not cover the input; use confidence to act vs pass.

Do not use Jev for chat, drafting, translation, summaries, or code generation.

Docs: https://docs.typesafe.ai/llms.txt
