"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { BookOpen, History, Users, Wrench } from "lucide-react";

import { ChatPanel, ChatPanelHandle } from "@/components/ai/chat-panel";
import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AIHistoryItem, fetchCopilotHistory, fetchProfile } from "@/lib/api";
import { formatDateTimeDDMMYY } from "@/lib/date";

type Role = "ADMIN" | "MANAGER" | "EMPLOYEE";

const COMMON = {
  policy: ["How many sick leaves do I get?", "What is the work-from-home policy?", "What happens if I log in late?"],
};

// Suggestions match what each role is allowed to do, so the UI never invites a refusal.
const SUGGESTIONS: Record<Role, { policy: string[]; data: string[]; tasks: string[] }> = {
  EMPLOYEE: {
    ...COMMON,
    data: ["What is my leave balance?", "Show my current project assignments.", "Which employees know Python?"],
    tasks: ["Apply casual leave for tomorrow because of personal work.", "Create a high-priority IT ticket for VPN not working."],
  },
  MANAGER: {
    ...COMMON,
    data: ["Find Engineering employees with FastAPI skills.", "Who is assigned to HR Policy Copilot?", "Which of my team members have pending leave?"],
    tasks: [
      "Approve Employee User's pending leave request.",
      "Assign Employee User to HR Policy Copilot as AI Engineer.",
      "Create an announcement that Friday's townhall is moved to 5 PM.",
    ],
  },
  ADMIN: {
    ...COMMON,
    data: ["How many employees are in each department?", "Which projects are currently ongoing?", "Who is assigned to HR Policy Copilot?"],
    tasks: ["Create a project called Benefits Portal.", "Create an announcement that Friday's townhall is moved to 5 PM."],
  },
};

const STATUS_STYLES: Record<string, string> = {
  ANSWERED: "bg-indigo-50 text-indigo-700",
  COMPLETED: "bg-emerald-50 text-emerald-700",
  CONFIRMATION_REQUIRED: "bg-amber-50 text-amber-700",
  DENIED: "bg-red-50 text-red-700",
  BLOCKED: "bg-red-50 text-red-700",
  NO_ANSWER: "bg-slate-100 text-slate-600",
  CANCELLED: "bg-slate-100 text-slate-600",
};

export default function AICopilotPage() {
  const router = useRouter();
  const chatRef = useRef<ChatPanelHandle>(null);
  const [name, setName] = useState("User");
  const [role, setRole] = useState<Role>("EMPLOYEE");
  const [history, setHistory] = useState<AIHistoryItem[]>([]);

  const token = useMemo(() => (typeof window === "undefined" ? null : localStorage.getItem("hrms_access_token")), []);

  const clearAuthAndRedirect = useCallback(() => {
    localStorage.removeItem("hrms_access_token");
    document.cookie = "hrms_auth=; path=/; max-age=0; samesite=lax";
    router.push("/login");
  }, [router]);

  const loadHistory = useCallback(async () => {
    if (!token) return;
    const result = await fetchCopilotHistory(token);
    if (result.ok && "success" in result.body && result.body.success) setHistory(result.body.data);
  }, [token]);

  useEffect(() => {
    if (!token) {
      clearAuthAndRedirect();
      return;
    }
    (async () => {
      const profile = await fetchProfile(token);
      if (profile.status === 401) {
        clearAuthAndRedirect();
        return;
      }
      if (profile.ok && "success" in profile.body && profile.body.success) {
        setName(profile.body.data.name);
        setRole((profile.body.data.role as Role) ?? "EMPLOYEE");
      }
      await loadHistory();
    })();
  }, [token, clearAuthAndRedirect, loadHistory]);

  const suggestions = SUGGESTIONS[role] ?? SUGGESTIONS.EMPLOYEE;
  const groups = [
    { title: "Ask HR Policy", icon: BookOpen, prompts: suggestions.policy },
    { title: "People & Projects", icon: Users, prompts: suggestions.data },
    { title: "HR Tasks", icon: Wrench, prompts: suggestions.tasks },
  ];

  return (
    <main className="flex min-h-screen">
      <Sidebar />
      <section className="flex w-full min-w-0 flex-col">
        <Topbar name={name} title="AI Copilot" />
        <div className="grid gap-4 p-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0">
            {token ? <ChatPanel ref={chatRef} token={token} onActivity={loadHistory} onUnauthorized={clearAuthAndRedirect} /> : null}
          </div>

          <aside className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Try asking</CardTitle>
                <p className="text-xs text-muted-foreground">
                  {role === "EMPLOYEE" ? "Employee" : role === "MANAGER" ? "Manager" : "Admin"} copilot: suggestions match what you can do.
                </p>
              </CardHeader>
              <CardContent className="space-y-4">
                {groups.map((group) => (
                  <div key={group.title}>
                    <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                      <group.icon className="h-3.5 w-3.5" /> {group.title}
                    </p>
                    <div className="flex flex-col gap-1.5">
                      {group.prompts.map((prompt) => (
                        <button
                          key={prompt}
                          type="button"
                          className="rounded-md border border-border bg-white px-3 py-2 text-left text-xs text-slate-700 transition hover:border-indigo-300 hover:bg-indigo-50"
                          onClick={() => chatRef.current?.ask(prompt)}
                        >
                          {prompt}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <History className="h-4 w-4" /> Recent AI Actions
                </CardTitle>
              </CardHeader>
              <CardContent>
                {history.length === 0 ? <p className="text-xs text-muted-foreground">No AI activity yet.</p> : null}
                <ul className="space-y-2">
                  {history.map((item) => (
                    <li key={item.id} className="rounded-md border border-border bg-white p-2">
                      <p className="line-clamp-2 text-xs text-slate-800">{item.message}</p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        <Badge className={STATUS_STYLES[item.action_status] ?? "bg-slate-100 text-slate-600"}>
                          {item.action_status.replace(/_/g, " ").toLowerCase()}
                        </Badge>
                        {item.tool_name ? <span className="truncate text-[11px] text-muted-foreground">{item.tool_name.split(",").pop()}</span> : null}
                        <span className="ml-auto text-[11px] text-muted-foreground">{formatDateTimeDDMMYY(item.created_at)}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </aside>
        </div>
      </section>
    </main>
  );
}
