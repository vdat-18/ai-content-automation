import {
  useLayoutEffect,
  useRef,
  type TextareaHTMLAttributes,
} from "react";

type AutoResizeTextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

function resizeTextarea(textarea: HTMLTextAreaElement) {
  textarea.style.height = "auto";
  textarea.style.height = `${textarea.scrollHeight}px`;
}

export function AutoResizeTextarea({
  onInput,
  value,
  ...props
}: AutoResizeTextareaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    if (textareaRef.current) resizeTextarea(textareaRef.current);
  }, [value]);

  return (
    <textarea
      {...props}
      ref={textareaRef}
      value={value}
      onInput={(event) => {
        resizeTextarea(event.currentTarget);
        onInput?.(event);
      }}
    />
  );
}
