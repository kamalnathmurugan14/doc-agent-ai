import type { ToolSpec } from "../api/client";

export function ToolList({ tools }: { tools: ToolSpec[] }) {
  return (
    <div className="tools">
      {tools.map((t) => (
        <article className="card" key={t.name}>
          <div className="row">
            <h3 style={{ margin: 0, flex: 1 }}>
              <code>{t.name}</code>
            </h3>
            <span className={`chip ${t.risk === "write" ? "warnchip" : "ok"}`}>{t.risk}</span>
            {t.requires_approval && <span className="chip">needs approval</span>}
          </div>
          <p>{t.description}</p>
          <table>
            <thead>
              <tr>
                <th>argument</th>
                <th>type</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {Object.entries(t.input_schema.properties ?? {}).map(([k, v]) => (
                <tr key={k}>
                  <td>
                    <code>{k}</code>
                  </td>
                  <td>
                    {v.type ?? "any"}
                    {t.input_schema.required?.includes(k) ? " · required" : ""}
                  </td>
                  <td className="muted">{v.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </article>
      ))}
    </div>
  );
}
