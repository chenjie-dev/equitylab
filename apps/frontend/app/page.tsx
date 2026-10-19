/**
 * 首页进入现货虚拟币行情。研究对话在 `/chat`。
 */
import { redirect } from "next/navigation";

export default function HomePage() {
  redirect("/markets");
}
