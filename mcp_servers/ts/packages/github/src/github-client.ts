import { Octokit } from "@octokit/rest";

let _client: Octokit | null = null;

export function getClient(token: string): Octokit {
  if (_client) return _client;
  _client = new Octokit({ auth: token });
  return _client;
}
