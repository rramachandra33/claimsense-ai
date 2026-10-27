import { redirect } from "next/navigation";

// The claim queue is the console's home page.
export default function Home() {
  redirect("/claims");
}
