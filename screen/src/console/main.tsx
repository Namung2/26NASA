import { createRoot } from "react-dom/client";
import "../shared/style.css";
import { ConsoleApp } from "./ConsoleApp";

createRoot(document.getElementById("root")!).render(<ConsoleApp />);
