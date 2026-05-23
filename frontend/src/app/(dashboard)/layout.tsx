import { Sidebar } from "@/components/sidebar";

const DashboardLayout = ({
  children,
}: Readonly<{ children: React.ReactNode }>) => {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 px-8 py-12 lg:px-14">
        <div className="max-w-[1400px]">{children}</div>
      </main>
    </div>
  );
};

export default DashboardLayout;
