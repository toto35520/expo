import Dashboard from "@/components/Dashboard";
import Login from "@/components/Login";
import { isAuthed, passwordConfigured } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function Page() {
  if (!(await isAuthed())) return <Login />;
  return <Dashboard passwordOn={passwordConfigured()} />;
}
