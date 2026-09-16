/** Theme/audience/brief/hook-line fields shared by the new/start/regenerate forms. */
export default function ThemeAudienceFields({ idPrefix }: { idPrefix: string }) {
  return (
    <>
      <label htmlFor={`${idPrefix}-theme`}>
        Theme
        <select id={`${idPrefix}-theme`} name="theme" defaultValue="training">
          <option value="training">training (CrossFit / Hyrox / funcional)</option>
          <option value="yoga">yoga</option>
        </select>
      </label>
      <label htmlFor={`${idPrefix}-audience`}>
        Audience
        <select id={`${idPrefix}-audience`} name="audience" defaultValue="prospects">
          <option value="prospects">prospects (sell the gym/class)</option>
          <option value="members">members (recognise the session)</option>
        </select>
      </label>
      <label htmlFor={`${idPrefix}-brief`}>
        Brief (optional; e.g. "Hyrox class, Thursday, 12 people, partner WOD")
        <input id={`${idPrefix}-brief`} type="text" name="brief" maxLength={200} />
      </label>
      <label htmlFor={`${idPrefix}-hook`}>
        Hook text (manual, skips the LLM)
        <input
          id={`${idPrefix}-hook`}
          type="text"
          name="hook_line"
          maxLength={40}
          placeholder="La barra despega del suelo"
        />
      </label>
    </>
  );
}
