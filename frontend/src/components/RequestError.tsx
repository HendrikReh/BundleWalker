// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import { ApiError } from "../api/client";

export function RequestError({ error }: { readonly error: unknown }) {
  const message = error instanceof ApiError ? error.message : "Request failed";
  return (
    <div className="request-error" role="alert">
      <strong>Request failed</strong>
      {message !== "Request failed" ? <p>{message}</p> : null}
    </div>
  );
}

export function PageRequestError({
  title,
  error,
}: {
  readonly title: string;
  readonly error: unknown;
}) {
  return (
    <section>
      <h1>{title}</h1>
      <RequestError error={error} />
    </section>
  );
}
