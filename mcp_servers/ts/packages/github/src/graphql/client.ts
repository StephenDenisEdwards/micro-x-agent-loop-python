import { graphql } from "@octokit/graphql";

let _graphqlClient: typeof graphql | null = null;

export function getGraphQLClient(token: string): typeof graphql {
  if (_graphqlClient) return _graphqlClient;
  _graphqlClient = graphql.defaults({
    headers: { authorization: `bearer ${token}` },
  });
  return _graphqlClient;
}

// Cache for repository node IDs and category IDs
const repoIdCache = new Map<string, string>();
const categoryCache = new Map<string, Array<{ id: string; name: string; emoji: string; description: string; isAnswerable: boolean }>>();
const labelCache = new Map<string, Array<{ id: string; name: string }>>();

export async function getRepoNodeId(gql: typeof graphql, owner: string, name: string): Promise<string> {
  const key = `${owner}/${name}`;
  const cached = repoIdCache.get(key);
  if (cached) return cached;

  const result = await gql<{ repository: { id: string } }>(
    `query GetRepoId($owner: String!, $name: String!) {
      repository(owner: $owner, name: $name) { id }
    }`,
    { owner, name },
  );

  repoIdCache.set(key, result.repository.id);
  return result.repository.id;
}

export async function getDiscussionCategories(
  gql: typeof graphql,
  owner: string,
  name: string,
): Promise<Array<{ id: string; name: string; emoji: string; description: string; isAnswerable: boolean }>> {
  const key = `${owner}/${name}`;
  const cached = categoryCache.get(key);
  if (cached) return cached;

  const result = await gql<{
    repository: {
      discussionCategories: {
        nodes: Array<{ id: string; name: string; emoji: string; description: string; isAnswerable: boolean }>;
      };
    };
  }>(
    `query GetCategories($owner: String!, $name: String!) {
      repository(owner: $owner, name: $name) {
        discussionCategories(first: 25) {
          nodes { id name emoji description isAnswerable }
        }
      }
    }`,
    { owner, name },
  );

  const categories = result.repository.discussionCategories.nodes;
  categoryCache.set(key, categories);
  return categories;
}

export async function resolveCategoryId(
  gql: typeof graphql,
  owner: string,
  name: string,
  categoryName: string,
): Promise<{ id: string; name: string } | null> {
  const categories = await getDiscussionCategories(gql, owner, name);
  return categories.find((c) => c.name.toLowerCase() === categoryName.toLowerCase()) ?? null;
}

export async function resolveLabelIds(
  gql: typeof graphql,
  owner: string,
  name: string,
  labelNames: string[],
): Promise<Array<{ id: string; name: string }>> {
  const key = `${owner}/${name}`;
  let allLabels = labelCache.get(key);

  if (!allLabels) {
    const result = await gql<{
      repository: { labels: { nodes: Array<{ id: string; name: string }> } };
    }>(
      `query GetLabels($owner: String!, $name: String!) {
        repository(owner: $owner, name: $name) {
          labels(first: 100) { nodes { id name } }
        }
      }`,
      { owner, name },
    );
    allLabels = result.repository.labels.nodes;
    labelCache.set(key, allLabels);
  }

  return allLabels.filter((l) => labelNames.some((n) => n.toLowerCase() === l.name.toLowerCase()));
}
