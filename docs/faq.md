---
title: FAQ
description: Short answers to the questions internal testers ask most.
---

# FAQ

## Where do I find my YID?

Open the YID app and go to **Settings**. Your YID is shown under the Yanez Guest Title.

## What is the base URL for agent authorization requests?

It depends on the environment you are pointing at:

| Environment | Base URL |
|---|---|
| Development | `https://dev3.yanezcompliance.com` |
| Test | `https://ptest.yanez.ai` |
| Production | `https://yid.yanez.ai` |

Every route in the [HTTP quickstart](http-quickstart.md) hangs off this base URL.
