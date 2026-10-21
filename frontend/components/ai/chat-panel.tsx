"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { AlertTriangle, Bot, Loader2, SendHorizontal, ShieldAlert, User } from "lucide-react";

import { ActionResultCard } from "@/components/ai/action-result-card";
import { SourceList } from "@/components/ai/source-list";
import { SqlResultTable } from "@/components/ai/sql-result-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AIActionResult,
  AIChatTurn,
  AIIntent,
  AIPolicyResult,
  AIRouterResult,
  AISqlResult,
  askCopilot,
  confirmCopilotAction,
} from "@/lib/api";

type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  text: string;
  intent?: AIIntent;
  routedBy?: "rules" | "llm";
  interpretedAs?: string | null;
  result?: AIRouterResult["result"];
  error?: { code: string; message: string };
};

export type ChatPanelHandle = { ask: (text: string) => void };

const INTENT_LABELS: Record<AIIntent, { label: string; className: string }> = {
  POLICY_QA: { label: "HR Policy", className: "bg-indigo-50 text-indigo-700" },
  SQL_QUERY: { label: "People & Projects", className: "bg-sky-50 text-sky-700" },
  HR_ACTION: { label: "HR Task", className: "bg-emerald-50 text-emerald-700" },
  UNKNOWN: { label: "Help", className: "bg-slate-100 text-slate-600" },
};

// Refusals and limits are expected outcomes, not crashes: show them calmly.
const REFUSAL_CODES = new Set(["FORBIDDEN", "READ_ONLY", "ACTION_NOT_SUPPORTED", "UNSAFE_REQUEST", "SQL_CANNOT_ANSWER"]);

const MAX_HISTORY_TURNS = 6;

export const ChatPanel = forwardRef<
  ChatPanelHandle,
  { token: string; onActivity?: () => void; onUnauthorized: () => void }
>(function ChatPanel({ token, onActivity, onUnauthorized }, ref) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [confirmingId, setConfirmingId] = useState<number | null>(null);
  const nextId = useRef(1);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

  const append = (message: Omit<ChatMessage, "id">) => {
    const id = nextId.current++;
    setMessages((current) => [...current, { ...message, id }]);
    return id;
  };

  const send = async (raw: string) => {
    const text = raw.trim();
    if (!text || sending) return;
    // Recent text-only turns let the assistant follow up on its own clarifying questions.
    const history: AIChatTurn[] = messages
      .filter((m) => !m.error)
      .slice(-MAX_HISTORY_TURNS)
      .map((m) => ({ role: m.role, content: (m.role === "assistant" ? m.result?.answer ?? m.text : m.text).slice(0, 2000) }));

    append({ role: "user", text });
    setInput("");
    setSending(true);
    try {
      const response = await askCopilot(token, text, history);
      if (response.status === 401) {
        onUnauthorized();
        return;
      }
      const body = response.body;
      if (body.success) {
        append({
          role: "assistant",
          text: body.data.result.answer,
          intent: body.data.intent,
          routedBy: body.data.routed_by,
          interpretedAs: body.data.interpreted_as,
          result: body.data.result,
        });
      } else {
        append({ role: "assistant", text: body.error?.message ?? "Something went wrong.", error: body.error ?? undefined });
      }
    } catch {
      append({ role: "assistant", text: "Couldn't reach the server. Check your connection and try again.", error: { code: "NETWORK", message: "" } });
    } finally {
      setSending(false);
      onActivity?.();
    }
  };

  useImperativeHandle(ref, () => ({ ask: (text: string) => void send(text) }));

  const decide = async (message: ChatMessage, approve: boolean) => {
    const action = message.result as AIActionResult;
    if (!action.confirmation_id) return;
    setConfirmingId(message.id);
    try {
      const response = await confirmCopilotAction(token, action.confirmation_id, approve);
      if (response.status === 401) {
        onUnauthorized();
        return;
      }
      const body = response.body;
      // The proposal card shows the outcome; on failure it is retired (the error explains why).
      const outcome: AIActionResult["status"] = !body.success ? "ANSWERED" : approve ? "COMPLETED" : "CANCELLED";
      setMessages((current) =>
        current.map((m) => (m.id === message.id ? { ...m, result: { ...action, status: outcome, confirmation_id: null } } : m))
      );
      if (body.success) {
        append({ role: "assistant", text: body.data.answer, intent: "HR_ACTION" });
      } else {
        append({ role: "assistant", text: body.error?.message ?? "The action failed.", error: body.error ?? undefined });
      }
    } finally {
      setConfirmingId(null);
      onActivity?.();
    }
  };

  return (
    <div className="flex h-[calc(100vh-11rem)] min-h-[32rem] flex-col rounded-xl border border-border bg-card shadow-sm">
      <div className="flex-1 space-y-4 overflow-y-auto p-5">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted-foreground">
            <Bot className="mb-3 h-10 w-10 text-indigo-400" />
            <p className="text-base font-medium text-slate-800">How can I help today?</p>
            <p className="mt-1 max-w-md">
              Ask about HR policies, look up people and projects, or ask me to do an HR task such as applying for leave.
            </p>
          </div>
        ) : null}

        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            busy={confirmingId === message.id}
            onDecision={(approve) => decide(message, approve)}
          />
        ))}

        {sending ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Thinking…
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>

      <form
        className="flex items-end gap-2 border-t border-border p-3"
        onSubmit={(event) => {
          event.preventDefault();
          void send(input);
        }}
      >
        <textarea
          aria-label="Message the AI Copilot"
          className="max-h-32 min-h-10 flex-1 resize-none rounded-md border border-border bg-white px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          placeholder="Ask a question or describe a task…"
          rows={1}
          maxLength={2000}
          value={input}
          disabled={sending}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send(input);
            }
          }}
        />
        <Button type="submit" disabled={sending || !input.trim()} aria-label="Send">
          <SendHorizontal className="h-4 w-4" />
        </Button>
      </form>
    </div>
  );
});

function MessageBubble({
  message,
  busy,
  onDecision,
}: {
  message: ChatMessage;
  busy: boolean;
  onDecision: (approve: boolean) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end gap-2">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-indigo-600 px-4 py-2 text-sm text-white">
          {message.text}
        </div>
        <span className="mt-1 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200 text-slate-600">
          <User className="h-4 w-4" />
        </span>
      </div>
    );
  }

  if (message.error) {
    const refusal = REFUSAL_CODES.has(message.error.code);
    const limited = message.error.code === "AI_RATE_LIMITED";
    return (
      <div className="flex gap-2">
        <span className="mt-1 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-indigo-600">
          <Bot className="h-4 w-4" />
        </span>
        <div
          role="alert"
          className={`flex max-w-[85%] items-start gap-2 rounded-2xl rounded-tl-sm border px-4 py-2 text-sm ${
            refusal || limited ? "border-amber-200 bg-amber-50 text-amber-900" : "border-red-200 bg-red-50 text-red-800"
          }`}
        >
          {refusal ? <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />}
          <span>{message.text}</span>
        </div>
      </div>
    );
  }

  const intent = message.intent ? INTENT_LABELS[message.intent] : null;
  const result = message.result;
  return (
    <div className="flex gap-2">
      <span className="mt-1 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-indigo-600">
        <Bot className="h-4 w-4" />
      </span>
      <div className="max-w-[85%] rounded-2xl rounded-tl-sm border border-border bg-white px-4 py-3 text-sm text-slate-800">
        {intent ? (
          <div className="mb-2 flex items-center gap-2">
            <Badge className={intent.className}>{intent.label}</Badge>
            {message.intent === "POLICY_QA" && result && "grounded" in result && !result.grounded ? (
              <Badge className="bg-slate-100 text-slate-600">Not in policy library</Badge>
            ) : null}
          </div>
        ) : null}
        {message.interpretedAs ? (
          <p className="mb-2 text-xs italic text-muted-foreground">Understood as: “{message.interpretedAs}”</p>
        ) : null}
        <p className="whitespace-pre-wrap leading-relaxed">{message.text}</p>
        {result && "sources" in result ? <SourceList sources={(result as AIPolicyResult).sources} /> : null}
        {result && "columns" in result ? <SqlResultTable result={result as AISqlResult} /> : null}
        {result && "status" in result ? (
          <ActionResultCard result={result as AIActionResult} busy={busy} onDecision={onDecision} />
        ) : null}
      </div>
    </div>
  );
}
