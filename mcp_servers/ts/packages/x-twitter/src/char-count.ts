/**
 * Tweet character counting using twitter-text.
 *
 * X uses weighted character counting:
 * - Standard text: 1 char each
 * - Emojis: 2 chars each
 * - URLs: always 23 chars regardless of length
 */

// twitter-text is a CJS module, use default import
import twitterText from "twitter-text";

export interface TweetParseResult {
  weightedLength: number;
  isValid: boolean;
  maxLength: number;
}

const MAX_TWEET_LENGTH = 280;

export function parseTweetText(text: string): TweetParseResult {
  const result = twitterText.parseTweet(text);
  return {
    weightedLength: result.weightedLength,
    isValid: result.valid,
    maxLength: MAX_TWEET_LENGTH,
  };
}
