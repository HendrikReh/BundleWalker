// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { useState } from "react";
import type { FormEvent } from "react";

import { useAsk } from "../../api/queries";
import { MarkdownContent } from "../../components/MarkdownContent";
import { OperationProgress } from "../../components/OperationProgress";
import { RequestError } from "../../components/RequestError";
import { SynthesisAction } from "./SynthesisAction";

const MAX_QUESTION_CHARACTERS = 20_000;
const MAX_MODEL_CHARACTERS = 255;

export function AskPage() {
  const [question, setQuestion] = useState("");
  const [model, setModel] = useState("");
  const ask = useAsk();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (ask.isPending) return;
    ask.mutate({
      question,
      model: model.trim() || null,
    });
  }

  const status = ask.isPending
    ? "Asking the knowledge base…"
    : ask.isError
      ? "Ask failed"
      : ask.data
        ? "Answer ready"
        : "";

  return (
    <section className="knowledge-workbench">
      <h1>Ask</h1>
      <p>Ask one read-only question and receive a cited answer.</p>
      <form onSubmit={submit}>
        <label htmlFor="ask-question">Question</label>
        <textarea
          id="ask-question"
          value={question}
          required
          maxLength={MAX_QUESTION_CHARACTERS}
          onChange={(event) => {
            setQuestion(event.currentTarget.value);
          }}
        />
        <label htmlFor="ask-model">Model (optional)</label>
        <input
          id="ask-model"
          value={model}
          maxLength={MAX_MODEL_CHARACTERS}
          onChange={(event) => {
            setModel(event.currentTarget.value);
          }}
        />
        <button type="submit" disabled={ask.isPending}>
          Ask
        </button>
        <SynthesisAction question={question} model={model} />
      </form>
      {status ? <OperationProgress message={status} /> : null}
      {ask.error ? <RequestError error={ask.error} /> : null}
      {ask.data ? (
        <article aria-labelledby="ask-answer-title">
          <h2 id="ask-answer-title">{ask.data.title}</h2>
          <MarkdownContent markdown={ask.data.markdown} />
        </article>
      ) : null}
    </section>
  );
}
