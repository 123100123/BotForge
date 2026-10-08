"use client";

import { forwardRef, useState, type ComponentProps } from "react";
import { EyeIcon, EyeOffIcon } from "lucide-react";
import { Input } from "@/components/ui/input";

/** Password input with a show/hide toggle at the end edge. The value stays left-to-right either way. */
export const PasswordField = forwardRef<HTMLInputElement, Omit<ComponentProps<"input">, "type" | "ref">>(function PasswordField(
  { className, ...props },
  ref,
) {
  const [shown, setShown] = useState(false);
  return (
    <div dir="ltr" className="relative">
      <Input ref={ref} type={shown ? "text" : "password"} dir="ltr" className={`pe-11 text-start ${className ?? ""}`} {...props} />
      <button
        type="button"
        onClick={() => setShown((v) => !v)}
        aria-pressed={shown}
        aria-label="نمایش گذرواژه"
        title={shown ? "پنهان کردن گذرواژه" : "نمایش گذرواژه"}
        className="absolute inset-y-0 end-0 grid w-10 place-items-center rounded-e-sm text-fg-muted transition-colors duration-fast hover:text-fg"
      >
        {shown ? <EyeOffIcon className="size-4" strokeWidth={1.75} aria-hidden /> : <EyeIcon className="size-4" strokeWidth={1.75} aria-hidden />}
      </button>
    </div>
  );
});
