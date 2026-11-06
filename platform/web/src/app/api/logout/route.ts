import { clearSession } from "@/lib/session";

export async function POST() {
  clearSession();
  // A relative Location, so the browser stays on the address it used (the EC2 public DNS, a
  // tunnel, localhost). request.url inside the container is the server's own address
  // (localhost:3100), which sent people on EC2 to their own machine. 303: follow with a GET.
  return new Response(null, { status: 303, headers: { Location: "/login" } });
}
