const THEMES = [
  { value: "training", title: "Training", hint: "CrossFit / Hyrox / funcional" },
  { value: "yoga", title: "Yoga", hint: "Flow / mobility / breath" },
] as const;

const AUDIENCES = [
  { value: "prospects", title: "Prospects", hint: "Sell the gym / class" },
  { value: "members", title: "Members", hint: "Recognise the session" },
] as const;

const BRIEF_CHIPS = [
  "Partner WOD",
  "12 people",
  "Morning class",
  "Competition prep",
  "Beginner friendly",
];

/** Step 2 of the new-session flow: prompt-first brief plus visual
 * theme/audience cards. Inputs keep the backend `brief`/`theme`/`audience`
 * names so `POST /api/sessions` is unchanged. */
export default function DescribeFields({
  brief,
  theme,
  audience,
  onBrief,
  onTheme,
  onAudience,
}: {
  brief: string;
  theme: string;
  audience: string;
  onBrief: (v: string) => void;
  onTheme: (v: string) => void;
  onAudience: (v: string) => void;
}) {
  function addChip(chip: string) {
    const next = brief.trim() ? `${brief.replace(/\s+$/, "")}, ${chip}` : chip;
    onBrief(next.slice(0, 200));
  }

  return (
    <div className="describe-fields">
      {" "}
      <label htmlFor="new-brief">
        What happened in this class? <span className="field-hint">{brief.length}/200</span>
        <textarea
          id="new-brief"
          name="brief"
          rows={3}
          maxLength={200}
          placeholder="Hyrox class, Thursday, 12 people, partner WOD…"
          value={brief}
          onChange={(e) => onBrief(e.target.value)}
        />
      </label>
      <div className="chip-row" aria-label="Brief shortcuts">
        {BRIEF_CHIPS.map((chip) => (
          <button key={chip} type="button" className="chip" onClick={() => addChip(chip)}>
            + {chip}
          </button>
        ))}
      </div>
      <fieldset>
        <legend>Theme</legend>
        <div className="card-options" role="radiogroup" aria-label="Theme">
          {THEMES.map((t) => (
            <label key={t.value} className={theme === t.value ? "is-picked" : undefined}>
              <input
                type="radio"
                name="theme"
                value={t.value}
                checked={theme === t.value}
                onChange={() => onTheme(t.value)}
              />
              <strong>{t.title}</strong>
              <span>{t.hint}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend>Audience</legend>
        <div className="card-options" role="radiogroup" aria-label="Audience">
          {AUDIENCES.map((a) => (
            <label key={a.value} className={audience === a.value ? "is-picked" : undefined}>
              <input
                type="radio"
                name="audience"
                value={a.value}
                checked={audience === a.value}
                onChange={() => onAudience(a.value)}
              />
              <strong>{a.title}</strong>
              <span>{a.hint}</span>
            </label>
          ))}
        </div>
      </fieldset>
    </div>
  );
}
