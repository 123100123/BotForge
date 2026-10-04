import { AuthForm } from "@/components/app/auth-form";

export const metadata = { title: "ورود | بات‌فورج" };

export default function LoginPage() {
  return <AuthForm mode="login" />;
}
