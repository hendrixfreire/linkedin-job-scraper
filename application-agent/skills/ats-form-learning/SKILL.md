---
name: ats-form-learning
description: "Use when a job application reaches an unknown ATS or employer form, or when adding/fixing an ATS adapter. It drives evidence-based form discovery, dry-run validation, and creates a reusable per-ATS form skill after verified learning."
---

# ATS Form Learning

## Objective

Turn each newly encountered ATS or recurring employer form into a verified, reusable capability without blocking the rest of the application pipeline.

## Operating loop

### 1. Triage the form

1. Identify the host, platform brand, form engine, and job URL.
2. Read the existing `ats-*-form` skill for that platform if it exists.
3. Classify the state: `known`, `unknown`, `login`, `captcha`, `2fa`, `closed`, or `unsupported-control`.
4. Persist factual evidence: URL, detected platform, timestamp, observed field labels/types, and blocker.

**Completion:** a factual state is recorded; an unknown form is never mislabeled as a missing URL.

### 2. Learn with bounded persistence

Work through the form in this order:

1. inspect public HTML/DOM and existing adapter tests;
2. try supported field primitives: text, textarea, native select, combobox, checkbox/radio, file upload;
3. use real user events only when a React-controlled field fails ordinary Playwright filling;
4. verify each committed field visually/through DOM state;
5. capture a sanitized fixture and a screenshot only when it contains no PII, answers, IDs, cookies, or tokens.

Retry equivalent controls using different safe selectors and interaction methods. Do not stop after a single selector failure.

**Hard gates:** never type passwords, copy cookies, bypass CAPTCHA/2FA, invent answers, accept legal terms, or submit while learning. When a hard gate appears, record it and leave the job blocked for the human; continue working on other eligible jobs and the reusable adapter offline.

**Completion:** either the form reaches a verified `dry_run` state, or the exact unresolved control/human gate is recorded with enough evidence for the next attempt.

### 3. Build or improve the adapter

1. Write a failing test using only synthetic or sanitized HTML.
2. Implement the smallest adapter/primitives change that satisfies it.
3. Add checks for required fields, upload confirmation, React state commitment, and unambiguous final submit control.
4. Run focused tests, then the complete suite.
5. Keep the ATS in `dry_run` until three distinct real forms complete without a material error.

**Completion:** tests are green and capability is explicitly `discovered`, `manual`, `dry_run`, or `auto_submit`; never infer promotion from a successful selector alone.

### 4. Write the reusable ATS skill

After a form has yielded verified learning, create or update `ats-<normalized-platform>-form` using `skill_manage`.

The child skill must contain:

- trigger and scope: hostnames/form family it applies to;
- prerequisite state and allowed automation mode;
- known field inventory with semantic labels, not personal values;
- interaction recipe for text, select/combobox, upload, and multi-step navigation;
- selector strategy and fallbacks, avoiding session-specific IDs;
- blockers and human gates;
- exact pre-submit and success confirmation signals;
- tests/fixture paths and validation commands;
- evidence date plus known limitations.

Use only generic placeholders such as `Candidate Name`, `candidate@example.com`, and `resume.pdf`. Never store a user profile, CV path, employer-private URL, access token, message/channel ID, screenshot with PII, or copied application answers in a skill.

**Completion:** the child skill exists, is factually grounded in a successful dry run or test, and can guide the next form without rediscovery.

## Queue rule

An unknown ATS must not stall the entire pipeline. Persist it in the adapter backlog and continue URL resolution/CV preparation/application work for every other eligible job.

## Promotion rule

`auto_submit` requires all of:

- green tests;
- three verified real dry runs on distinct jobs;
- no unresolved login, CAPTCHA, 2FA, or sensitive required question;
- explicit user authorization for that ATS.
