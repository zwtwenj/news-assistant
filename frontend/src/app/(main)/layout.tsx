import Sidebar from "@/components/Sidebar";

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-1 bg-zinc-50 dark:bg-zinc-950">
      <Sidebar />
      <main className="min-w-0 flex-1 px-6 py-6">{children}</main>
    </div>
  );
}
