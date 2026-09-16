/** Optional brand fieldset (logo/handle/second line) shared by new/regenerate forms. */
export default function BrandFieldset({
  idPrefix,
  legend,
}: {
  idPrefix: string;
  legend: string;
}) {
  return (
    <fieldset>
      <legend>{legend}</legend>
      <label htmlFor={`${idPrefix}-logo`}>
        Logo (PNG with alpha)
        <input id={`${idPrefix}-logo`} type="file" name="logo" accept="image/png" />
      </label>
      <label htmlFor={`${idPrefix}-handle`}>
        Handle
        <input
          id={`${idPrefix}-handle`}
          type="text"
          name="handle"
          maxLength={40}
          placeholder="@migimnasio"
        />
      </label>
      <label htmlFor={`${idPrefix}-line`}>
        Second line
        <input
          id={`${idPrefix}-line`}
          type="text"
          name="line"
          maxLength={60}
          placeholder="C/ Toro 12 · Salamanca"
        />
      </label>
    </fieldset>
  );
}
