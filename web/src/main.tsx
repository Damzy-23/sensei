import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App, Logo } from "./App";
import { AppProvider } from "./app-context";
import { AuthProvider, SignInGate } from "./auth";
import "./theme.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider>
      <SignInGate logo={<Logo />}>
        <AppProvider>
          <App />
        </AppProvider>
      </SignInGate>
    </AuthProvider>
  </StrictMode>,
);
