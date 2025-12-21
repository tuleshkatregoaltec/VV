"""LLMLingua Compression Service - Semantic compression for conversation history."""

from llmlingua import PromptCompressor
from typing import List, Dict, Tuple
import logging

logger = logging.getLogger(__name__)


class MessageCompressor:
    """Semantic compression using LLMLingua"""

    def __init__(self):
        # Initialize with LLMLingua-2 model for better quality
        try:
            self.compressor = PromptCompressor(
                model_name="microsoft/llmlingua-2-xlm-roberta-large-meetingbank",
                use_llmlingua2=True,  # Use LLMLingua-2 for better quality
            )
            logger.info("LLMLingua compressor initialized successfully")
        except Exception as e:
            logger.warning(
                f"Failed to initialize LLMLingua compressor: {e}. Compression will be disabled."
            )
            self.compressor = None

    def compress_conversation_history(
        self,
        messages: List[Dict[str, str]],
        target_token: int = 1000,
        instruction: str = "Compress the conversation history while preserving key information about real estate data, queries, and analysis.",
    ) -> Tuple[List[Dict[str, str]], float]:
        """Compress conversation history for context window management.

        Args:
            messages: List of {role, content} dicts
            target_token: Target token count after compression
            instruction: Instruction for compression

        Returns:
            Tuple of (compressed_messages, compression_ratio)
        """
        if not self.compressor:
            logger.warning("Compressor not initialized, returning original messages")
            return messages, 1.0

        try:
            # Combine messages into single context for compression
            context_parts = []
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                context_parts.append(f"{role}: {content}")

            full_context = "\n\n".join(context_parts)

            # Compress
            compressed_result = self.compressor.compress_prompt(
                full_context,
                instruction=instruction,
                target_token=target_token,
                condition_compare=True,
                condition_in_question="none",
                rank_method="llmlingua",
                use_sentence_level_filter=False,
                use_context_level_filter=False,
                use_token_level_filter=True,
                concate_question=False,
            )

            compressed_text = compressed_result["compressed_prompt"]
            ratio = compressed_result.get("ratio", 1.0)

            # Re-package as system message
            compressed_messages = [
                {
                    "role": "system",
                    "content": f"[Previous conversation compressed for context]:\n{compressed_text}",
                }
            ]

            logger.info(f"Compressed {len(messages)} messages with ratio {ratio:.2f}")
            return compressed_messages, ratio

        except Exception as e:
            logger.exception("Compression failed, returning original messages")
            return messages, 1.0

    def should_compress(
        self, messages: List[Dict[str, str]], threshold: int = 3000
    ) -> bool:
        """Determine if compression is needed based on token count estimation.

        Args:
            messages: List of messages to evaluate
            threshold: Token count threshold to trigger compression

        Returns:
            True if compression should be applied
        """
        # Rough estimation: 4 characters per token
        total_chars = sum(len(msg.get("content", "")) for msg in messages)
        estimated_tokens = total_chars / 4
        should_compress = estimated_tokens > threshold

        if should_compress:
            logger.info(
                f"Estimated tokens ({estimated_tokens:.0f}) exceeds threshold ({threshold}), compression recommended"
            )

        return should_compress


# Global compressor instance
compressor = MessageCompressor()
