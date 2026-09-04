---
title: Use with AI agents
description: Every page has a raw-markdown twin, and a compact agent reference lives at llms.txt. Point any assistant or coding agent at them.
---

# Use with AI agents

Every page on this site has a raw-markdown twin, and a compact agent reference lives
at `llms.txt`. Point a chat assistant or a coding agent at either and it can help you
wire agent authorization into your stack. There is nothing to install.

<p><a class="button" href="https://yanez-compliance.github.io/yanez-agent-authorization/llms.txt">Open llms.txt</a></p>

The file follows the [llms.txt convention](https://llmstxt.org/): a short summary, the
facts an agent must not get wrong (who verifies the receipt, the four routes, the
credential rule), and links to every doc, SDK README, and example as raw markdown.

## On every page

The toolbar at the top of every page is a one-click handoff:

- **Copy page** copies the page's raw markdown to your clipboard. Paste it into any chat.
- **View as Markdown** opens the raw `.md` source so you can save it or pipe it somewhere.
- **Open in Claude** and **Open in ChatGPT** start a new chat with a prompt that points
  the assistant at the page.
- **llms.txt** opens the agent reference.

If your assistant can fetch URLs, prefer that over pasting: it stays in sync when the
docs change.

## For a chat session

Paste this into Claude, ChatGPT, Gemini, or any other assistant to seed the session:

```text
You are helping me integrate Yanez agent authorization: an AI agent requests
verifiable human approval for a sensitive action, and the action executor verifies
the signed receipt before acting.

Start by reading https://yanez-compliance.github.io/yanez-agent-authorization/llms.txt,
then follow its links to the pages relevant to my task. Then help me with my task.
```

## For a coding agent

Coding agents read a rules file from your repository on startup. Add the following
block to whichever file your agent reads:

- **Claude Code**: `CLAUDE.md`
- **Codex, OpenCode**: `AGENTS.md`
- **Cursor**: `.cursor/rules/yanez.md`
- **GitHub Copilot**: `.github/copilot-instructions.md`

```markdown
# Yanez agent authorization: agent context

Before touching Yanez agent-authorization code, read
https://yanez-compliance.github.io/yanez-agent-authorization/llms.txt and the pages
it links for the task at hand.

Rules that must hold in any code you write:

- A receipt authorizes nothing by itself. The action executor verifies the signature,
  compares the signed terms with the proposed action by deep JSON equality, applies
  its own freshness policy, and consumes single-use receipts. Gate single-use actions
  on `consumed_now: true`, never on `valid: true` alone.
- The `yak_` agent key comes from configuration (`YANEZ_AGENT_API_KEY` or a secret
  manager), never from prompts, tool arguments, command-line flags, or logs. Never
  pass it to a sub-agent.
- Send a random `Idempotency-Key` on every create and reuse it verbatim on retries.
  Never derive it from the request content.
- Stop on `rejected` or `expired`. Never create replacement requests in a loop.
```

## Fetch the docs as markdown

Every page's raw markdown lives in the repository. Swap the site URL for the raw
GitHub URL:

```sh
BASE=https://raw.githubusercontent.com/yanez-compliance/yanez-agent-authorization/main

curl "$BASE/docs/integration-options.md"              # choosing an integration path
curl "$BASE/docs/http-quickstart.md"                  # the four HTTP routes
curl "$BASE/docs/terms-and-receipts.md"               # what the human approves; receipt claims
curl "$BASE/docs/action-enforcement.md"               # the action executor's contract
curl "$BASE/openapi/agent-authorization.openapi.yaml" # full request and response schemas

# The agent reference
curl https://yanez-compliance.github.io/yanez-agent-authorization/llms.txt
```
