"""GraphQL documents used by the Buffer client."""

CREATE_POST_QUERY = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess {
      post {
        id
        text
        dueAt
        assets { id mimeType }
      }
    }
    ... on MutationError {
      message
    }
  }
}
"""

EDIT_POST_QUERY = """
mutation EditPost($input: EditPostInput!) {
  editPost(input: $input) {
    ... on PostActionSuccess {
      post {
        id
        text
        dueAt
        status
        assets { id type mimeType source thumbnail }
      }
    }
    ... on MutationError {
      message
    }
  }
}
"""

DELETE_POST_QUERY = """
mutation DeletePost($input: DeletePostInput!) {
  deletePost(input: $input) {
    ... on DeletePostSuccess {
      id
    }
    ... on VoidMutationError {
      message
    }
  }
}
"""

GET_CHANNELS_QUERY = """
query GetChannels($organizationId: OrganizationId!) {
  channels(input: {
    organizationId: $organizationId,
    filter: { isLocked: false }
  }) {
    id
    name
    displayName
    service
  }
}
"""

GET_AGGREGATED_POST_METRICS_QUERY = """
query GetAggregatedPostMetrics($input: AggregatedPostMetricsInput!) {
  aggregatedPostMetrics(input: $input) {
    metrics {
      type
      name
      value
      unit
      description
    }
    metricsUpdatedAt
  }
}
"""

GET_POSTS_QUERY = """
query GetPosts($input: PostsInput!, $first: Int!, $after: String) {
  posts(input: $input, first: $first, after: $after) {
    edges {
      node {
        id
        text
        channelId
        status
        createdAt
        updatedAt
        dueAt
        sentAt
        externalLink
        via
        tags { id name color }
        assets { id type mimeType source thumbnail }
        metadata {
          __typename
          ... on InstagramPostMetadata { type shouldShareToFeed }
          ... on FacebookPostMetadata { type }
        }
        metrics {
          type
          name
          value
          unit
          description
        }
        metricsUpdatedAt
      }
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
"""
