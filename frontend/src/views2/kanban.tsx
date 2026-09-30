import { useState } from "react";
import { api, BoardColumn, BoardMission } from "../api";
import { useStore } from "../store";
import { useFetch } from "../views1";
import { Btn, Empty, Icon, Panel, Pill, Row } from "../ui";

const NEXT: Record<string, { col: string; label: string }[]> = {
  backlog: [{ col: "running", label: "Start" }, { col: "done", label: "Cancel" }],
  running: [{ col: "backlog", label: "Pause" }, { col: "done", label: "Cancel" }],
  awaiting: [{ col: "backlog", label: "Pause" }, { col: "done", label: "Cancel" }],
  done: [],
};

export function KanbanView() {
  const { toast } = useStore();
  const { data, reload } = useFetch(() => api.board.get());
  const [over, setOver] = useState<string | null>(null);
  const [dragId, setDragId] = useState<number | null>(null);

  const move = async (m: BoardMission, col: string) => {
    try {
      await api.board.move(m.id, col);
      reload();
      toast(`Moved “${m.goal.slice(0, 40)}”`, "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const cols: BoardColumn[] = data?.columns || [];

  return (
    <div className="view">
      <div className="vhead">
        <h2><Icon n="rocket" s={20} /> Missions Board</h2>
        <Pill c="violet">
          {Object.values(data?.counts || {}).reduce((a, b) => a + b, 0)} missions
        </Pill>
      </div>
      <div className="board" data-testid="board">
        {cols.map((c) => (
          <section
            key={c.key}
            aria-label={c.label}
            className={`boardcol ${over === c.key ? "over" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setOver(c.key); }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(null);
              if (dragId === null) return;
              const card = c.missions.find((m) => m.id === dragId);
              setDragId(null);
              if (card) void move(card, c.key);
            }}
          >
            <header><strong>{c.label}</strong><Pill c="blue">{c.missions.length}</Pill></header>
            {c.missions.map((m) => (
              <div
                key={m.id}
                className="boardcard"
                draggable
                onDragStart={(e) => { setDragId(m.id); e.dataTransfer.setData("text/plain", String(m.id)); }}
                onDragEnd={() => setDragId(null)}
              >
                <strong>{m.goal}</strong>
                <small>{m.steps_done}/{m.steps_total} steps · {m.status}</small>
                <Row icon="clock"
                  title={m.next_run_at ? `Next ${m.next_run_at.slice(0, 16).replace("T", " ")}` : "No schedule"} />
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {(NEXT[c.key] || []).map((a) => (
                    <Btn key={a.col} small onClick={() => move(m, a.col)}>{a.label}</Btn>
                  ))}
                </div>
              </div>
            ))}
            {c.missions.length === 0 && <Empty title="Empty" sub="Nothing here yet." />}
          </section>
        ))}
        {cols.length === 0 && <Empty title="Loading board" sub="Fetching missions…" />}
      </div>
      <Panel icon="shield" title="How moves work" sub="The board cannot fake success">
        <small className="dim">
          A card dragged out of the backlog without starting is cancelled, not completed. The only
          route to Finished is a mission actually finishing, so the board can never mark work done
          that AURA did not do. Cards needing approval stay in Needs you until you resolve them in
          Activity.
        </small>
      </Panel>
    </div>
  );
}
