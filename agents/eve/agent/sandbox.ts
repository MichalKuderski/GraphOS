import { defineSandbox } from "eve/sandbox";
import { JustBashSandbox } from "eve/sandbox/just-bash";

// eve requires an environment. No shell/file tools expose it to this model.
// This virtual filesystem has no native process access or mounted host paths.
export const environment = JustBashSandbox.environment({autoInstall: false});
export default defineSandbox(() => environment.open());
