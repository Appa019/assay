import { Sidebar } from "@/components/sidebar";
import { MobileNav } from "@/components/mobile-nav";
import { NotificationsBell } from "@/components/notifications-bell";

const DashboardLayout = ({
  children,
}: Readonly<{ children: React.ReactNode }>) => {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      {/* min-w-0 lets wide children scroll inside instead of stretching the
          page; the bottom padding clears the mobile tab bar. */}
      <main className="flex-1 min-w-0 px-5 pt-7 pb-28 md:px-8 md:py-12 md:pb-12 lg:px-14">
        <div className="max-w-[1400px]">{children}</div>
      </main>
      <NotificationsBell variant="floating" />
      <MobileNav />
    </div>
  );
};

export default DashboardLayout;
