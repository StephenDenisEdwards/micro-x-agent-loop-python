import { Octokit } from "@octokit/rest";
import { retry } from "@octokit/plugin-retry";
import { throttling } from "@octokit/plugin-throttling";

const ResilientOctokit = Octokit.plugin(retry, throttling);

let _client: Octokit | null = null;

export function getClient(token: string): Octokit {
  if (_client) return _client;
  _client = new ResilientOctokit({
    auth: token,
    retry: { retries: 3 },
    throttle: {
      onRateLimit: (retryAfter, options, _octokit, retryCount) => {
        // Retry primary rate-limit hits up to 3 times
        if (retryCount < 3) {
          return true;
        }
        return false;
      },
      onSecondaryRateLimit: (retryAfter, options, _octokit, retryCount) => {
        // Retry secondary (abuse) rate limits up to 2 times
        if (retryCount < 2) {
          return true;
        }
        return false;
      },
    },
  });
  return _client;
}
