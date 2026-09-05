import AdminSidebar from "@/components/admin/AdminSidebar";

export default function AdminPanelLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-zinc-100 dark:bg-zinc-950">
      <AdminSidebar />
      <main className="flex-1 overflow-x-auto px-8 py-6">{children}</main>
    </div>
  );
}
