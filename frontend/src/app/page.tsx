import { redirect } from "next/navigation";

/** The portal has no marketing surface; everything starts at the imaging screen. */
export default function Home() {
  redirect("/studies");
}
