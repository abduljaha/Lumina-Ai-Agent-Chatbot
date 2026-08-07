import { Outlet } from "react-router-dom";
import { Sidebar } from "@/components/sidebar/sidebar";

export function ChatLayout() {
  return (
    <div className="relative z-10 flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
