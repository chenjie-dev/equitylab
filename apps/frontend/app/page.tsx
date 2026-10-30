/**
 * 首页进入加密货币现货行情。研究对话在 `/chat`。
 */
import { redirect } from "next/navigation";

export default function HomePage() {
  redirect("/markets");
}
