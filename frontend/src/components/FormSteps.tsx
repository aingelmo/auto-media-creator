/** Clickable step header for a wizard-style form. Presentational only —
 * the caller owns which step is current and how to validate a jump. */
export default function FormSteps({
  steps,
  current,
  onJump,
}: {
  steps: readonly string[];
  current: number;
  onJump: (i: number) => void;
}) {
  return (
    <ol className="form-steps">
      {steps.map((title, i) => (
        <li
          key={title}
          className={i < current ? "is-done" : i === current ? "is-current" : undefined}
        >
          <button
            type="button"
            aria-current={i === current ? "step" : undefined}
            onClick={() => onJump(i)}
          >
            <span className="form-steps-num" aria-hidden="true">
              {i < current ? "✓" : i + 1}
            </span>{" "}
            {title}
          </button>
        </li>
      ))}
    </ol>
  );
}
