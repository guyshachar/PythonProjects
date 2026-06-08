"""
Poll Service for creating and managing polls with multiple questions and answers.

This service allows you to:
- Create polls with multiple questions
- Each question can have multiple answer options
- Send polls via messaging service (Meta, Twilio, etc.)
- Collect votes from users
- Store votes in Redis
- Get poll results and statistics
"""

import uuid
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import sys
from urllib.parse import quote, unquote
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.logger import Logger
from shared.db import CacheService
from shared.messaging.messagingService import MessagingService

class PollService:
    """Service for creating and managing polls with multiple questions"""
    
    def __init__(self, logger: Logger, cacheService: CacheService, messagingService: MessagingService):
        """
        Initialize PollService
        
        Args:
            logger: Logger instance
            cacheService: CacheService instance for Redis operations
            messagingService: MessagingService instance for sending messages
        """
        self.logger = logger
        self.cacheService = cacheService
        self.messagingService = messagingService
        self.poll_prefix = "poll"
        self.vote_prefix = "poll_vote"
        self.default_ttl_seconds = 30 * 24 * 60 * 60  # 30 days default TTL
    
    def create_poll(
        self,
        poll_title: str,
        questions: List[Dict[str, Any]],
        description: Optional[str] = None,
        expires_in_days: int = 7,
        allow_multiple_answers_per_question: bool = False,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a new poll with multiple questions
        
        Args:
            poll_title: Title of the poll
            questions: List of question dictionaries, each with:
                - 'question': str - The question text
                - 'answers': List[str] - List of answer options
                - 'question_id': str (optional) - Custom question ID, auto-generated if not provided
            description: Optional description of the poll
            expires_in_days: Number of days until poll expires (default: 7)
            allow_multiple_answers_per_question: Whether users can select multiple answers per question
            metadata: Optional metadata to store with the poll
        
        Returns:
            poll_id: Unique identifier for the poll
            
        Example:
            questions = [
                {
                    'question_id': 'q1',
                    'question_text': 'What is your name ?',
                    'question_description': 'Please enter your name',
                    'question_type': 'text',
                },
                {
                    'question_id': 'q2',
                    'question_text': 'What is your favorite sport?',
                    'question_description': 'Please select your favorite sport',
                    'question_type': 'single_choice',
                    'answers': ['Football', 'Basketball', 'Tennis', 'Swimming']
                },
                {
                    'question_id': 'q3',
                    'question_text': 'How often do you play?',
                    'question_description': 'Please select your frequency of play',
                    'question_type': 'single_choice',
                    'answers': ['Daily', 'Weekly', 'Monthly', 'Rarely']
                },
            ]
            poll_id = poll_service.create_poll(
                poll_title='Sports Survey',
                questions=questions,
                expires_in_days=14
            )
        """
        try:
            poll_id = str(uuid.uuid4())
            now = helpers.localNow()
            expires_at = now + timedelta(days=expires_in_days)
            
            # Validate and process questions
            processed_questions = []
            for idx, question in enumerate(questions):
                if 'question_text' not in question:
                    raise ValueError(f"Question {idx} must have 'question_text' field")
                
                question_id = question.get('question_id') or f"q_{idx + 1}"
                question_type = question.get('question_type') or 'single_choice'

                if question_type != 'text' and 'answers' not in question:
                    raise ValueError(f"Question {idx} 'answers' fields")

                answers = question.get('answers', [])
                
                if question_type == 'single_choice' and (not isinstance(answers, list) or len(answers) < 2):
                    raise ValueError(f"Question {idx} must have at least 2 answer options")
                
                processed_question = {
                    'question_id': question_id,
                    'question_text': question['question_text'],
                    'question_description': question.get('question_description', ''),
                    'question_type': question_type,
                    'answers': answers,
                    'answer_ids': [f"{question_id}#a#{i+1}" for i in range(len(answers))]
                }
                processed_questions.append(processed_question)
            
            poll_data = {
                'poll_id': poll_id,
                'title': poll_title,
                'description': description,
                'questions': processed_questions,
                'expires_at': expires_at.isoformat(),
                'allow_multiple_answers_per_question': allow_multiple_answers_per_question,
                'status': 'active',
                'total_votes': 0,
                'metadata': metadata or {}
            }
            
            # Store poll in Redis
            success = self.cacheService.setPoll(pollId=poll_id, value=poll_data)
            
            if success:
                self.logger.info(f"✅ Created poll {poll_id}: {poll_title} with {len(processed_questions)} questions")
                return poll_id
            else:
                raise Exception("Failed to save poll to Redis")
                
        except Exception as ex:
            self.logger.error(f"❌ Error creating poll: {ex}", ex)
            raise
    
    def get_poll(self, pollId: str) -> Optional[Dict[str, Any]]:
        """Get poll data by poll_id"""
        try:
            poll_data = self.cacheService.getPolls(pollId=pollId)
            self.logger.debug(f"Poll {pollId} data: {poll_data}")
            return poll_data
        except Exception as ex:
            self.logger.error(f"❌ Error getting poll {pollId}: {ex}", ex)
            return None
    
    async def send_poll(
        self,
        poll_id: str,
        to: str,
        send_all_questions: bool = False,
        question_index: int = 0
    ) -> Optional[str]:
        """
        Send a poll question to a user via messaging service
        
        Args:
            poll_id: ID of the poll to send
            to: Recipient phone number or user identifier
            send_all_questions: If True, sends all questions sequentially. If False, sends one question at a time
            question_index: Index of question to send (0-based), only used if send_all_questions=False
        
        Returns:
            message_id: Message ID from messaging service, or None if failed
        """
        try:
            poll_data = self.get_poll(pollId=poll_id)
            if not poll_data:
                self.logger.error(f"❌ Poll {poll_id} not found")
                return None
            
            if poll_data.get('status') != 'active':
                self.logger.warning(f"⚠️ Poll {poll_id} is not active (status: {poll_data.get('status')})")
                return None
            
            questions = poll_data.get('questions', [])
            if not questions:
                self.logger.error(f"❌ Poll {poll_id} has no questions")
                return None
            
            if send_all_questions:
                # Send all questions sequentially
                message_ids = []
                for idx, question_data in enumerate(questions):
                    msg_id = await self._send_single_question(
                        poll_id=poll_id,
                        question_data=question_data,
                        question_index=idx,
                        total_questions=len(questions),
                        to=to,
                        poll_title=poll_data.get('title', 'Poll')
                    )
                    if msg_id:
                        message_ids.append(msg_id)
                    # Small delay between messages
                    import time
                    time.sleep(0.5)
                return message_ids[0] if message_ids else None
            else:
                # Send single question
                if question_index >= len(questions):
                    self.logger.error(f"❌ Question index {question_index} out of range")
                    return None
                
                question_data = questions[question_index]
                msgSid = await self._send_single_question(
                    poll_id=poll_id,
                    question_data=question_data,
                    question_index=question_index,
                    total_questions=len(questions),
                    to=to,
                    poll_title=poll_data.get('title', 'Poll')
                )
                return msgSid

        except Exception as ex:
            self.logger.error(f"❌ Error sending poll {poll_id}: {ex}", ex)
            return None
    
    async def _send_single_question(
        self,
        poll_id: str,
        question_data: Dict[str, Any],
        question_index: int,
        total_questions: int,
        to: str,
        poll_title: str
    ) -> Optional[str]:
        """Send a single question with answer buttons"""
        try:
            question_id = question_data['question_id']
            question_text = question_data['question_text']
            question_description = question_data['question_description']
            question_type = question_data['question_type']
            answers = question_data['answers']
            answer_ids = question_data['answer_ids']
            
            # Format question text
            body = ''
            if question_type == 'text':
                body += f"*{poll_title}*\n\n"
            if total_questions > 1:
                body += f"שאלה {question_index + 1} מתוך {total_questions}:\n\n"
            body += f"*{question_text}*"
            if question_description:
                body += f"\n{question_description}"
            
            customData = {
                'action': 'pollVote',
                'poll_id': poll_id,
                'question_index': question_index,
                'question_id': question_id
            }

            msgSid = None

            # Create buttons for answers
            if question_type == 'single_choice':
                promptButtons = []
                for idx, (answer, answer_id) in enumerate(zip(answers, answer_ids)):
                    promptButtons.append({
                        "sub_type": "quick_reply",
                        "id": f"pollVote_{poll_id}_{question_index}_{question_id}_{answer_id}",
                        "text": answer,  # Limit button text length
                    })
                
                # Send interactive message
                msgSid = self.messagingService.sendInteractiveMessage(
                    to=to,
                    header=poll_title,
                    question=body,
                    promptButtons=promptButtons,
                    customData=customData,
                )
            
            elif question_type == 'text':
                msgSid = await self.messagingService.sendMessage(to=to, message=body)
                if msgSid and customData:
                    self.logger.info(f"📤 Setting reference ID for message {msgSid} with custom data {customData}")
                    self.cacheService.setReferenceId(target='msgSid', id=msgSid, value=customData)
            
            else:
                raise ValueError(f"Invalid question type: {question_type}")
                
            return msgSid
            
        except Exception as ex:
            self.logger.error(f"❌ Error sending single question: {ex}", ex)
            return None
    
    def allow_vote(self, pollId: str, mobileNo: str, questionId: str) -> bool:
        """Get existing vote for a poll question"""
        try:
            poll_data = self.get_poll(pollId=pollId)
            if not poll_data:
                return False
            existing_vote = self.cacheService.getPollVotes(pollId=pollId, mobileNo=mobileNo, questionId=questionId)
            allow_multiple = poll_data.get('allow_multiple_answers_per_question', False)
            return allow_multiple or not existing_vote
        except Exception as ex:
            self.logger.error(f"❌ Error getting existing vote: {ex}", ex)
            return False
    
    def record_vote(
        self,
        poll_id: str,
        question_index: int,
        question_id: str,
        answer: str,
        mobileNo: str,
    ) -> bool:
        """
        Record a vote for a poll question
        
        Args:
            poll_id: ID of the poll
            question_id: ID of the question
            answer: ID of the selected answer or text answer
            mobileNo: Unique identifier for the user (e.g., phone number)
        
        Returns:
            True if vote was recorded successfully, False otherwise
        """
        try:
            self.logger.info(f"Recording vote for poll {poll_id}, question {question_index}, question {question_id}, answer {answer}, mobileNo {mobileNo}")
            
            poll_data = self.get_poll(pollId=poll_id)
            if not poll_data:
                self.logger.error(f"❌ Poll {poll_id} not found")
                return False
            
            if poll_data.get('status') != 'active':
                self.logger.warning(f"⚠️ Cannot vote on inactive poll {poll_id}")
                return False
            
            question = poll_data.get('questions', [])[question_index]

            allow_vote = self.allow_vote(pollId=poll_id, mobileNo=mobileNo, questionId=question_id)
            
            if not allow_vote:
                self.logger.info(f"ℹ️ השופט {mobileNo} כבר ענה על שאלה {question_id} בסקר {poll_id}")
                return True
            
            # Record vote
            vote_data = {
                'answer': answer,
            }
            
            # Store vote
            success = self.cacheService.setPollVote(
                pollId=poll_id,
                mobileNo=mobileNo,
                questionId=question_id,
                value=vote_data
            )
            
            if success:
                # Update vote count for this specific answer
                vote_count_key = f"{self.vote_prefix}:count:{poll_id}:{question_id}:{answer}"
                count_data = self.cacheService._redis_get(key=vote_count_key)
                current_count = int(count_data.get('count', '0')) if count_data else 0
                self.cacheService._redis_set(
                    key=vote_count_key,
                    data={'count': current_count + 1},
                    ttl_seconds=self.default_ttl_seconds
                )
                
                # Update poll total vote count
                poll_data['total_votes'] = int(poll_data.get('total_votes', '0')) + 1
                self.cacheService.setPoll(
                    pollId=poll_id,
                    value=poll_data
                )
                
                # Store user in voters set for this poll
                voters_key = f"{self.vote_prefix}:voters:{poll_id}"
                voters_data = self.cacheService._redis_get(key=voters_key)
                voters_set = set(voters_data.get('voters', [])) if voters_data else set()
                voters_set.add(mobileNo)
                self.cacheService._redis_set(
                    key=voters_key,
                    data={'voters': list(voters_set)},
                    ttl_seconds=self.default_ttl_seconds
                )
                
                self.logger.info(f"✅ Recorded vote: User {mobileNo} voted {answer} on question {question_id} in poll {poll_id}")
                return True
            else:
                return False
                
        except Exception as ex:
            self.logger.error(f"❌ Error recording vote: {ex}", ex)
            return False
    
    async def process_vote_from_message(
        self,
        messageBody: str,
        buttonId: str,
        customData: Optional[Dict[str, Any]],
        mobileNo: str,
        auto_send_next_question: bool = True
    ) -> bool:
        """
        Process a vote from a message payload (e.g., button click)
        
        Args:
            message_payload: Payload from button click (format: poll_{poll_id}_{answer_id})
            mobileNo: User identifier
            auto_send_next_question: If True, automatically sends the next question after recording vote
        
        Returns:
            True if vote was processed successfully
        """
        try:
            self.logger.info(f"Processing vote from message: {messageBody}, buttonId: {buttonId}, customData: {customData}, mobileNo: {mobileNo}")

            if messageBody and messageBody.startswith('pollVote_'):
                parts = messageBody.split('_')
                if len(parts) < 2:
                    self.logger.warning(f"⚠️ Invalid poll vote request: {messageBody}")
                    return '❌ שגיאה בקריאה לסקר.'
                
                poll_id = parts[1]
                await self.send_poll(poll_id=poll_id, to=mobileNo, send_all_questions=False, question_index=0)
                return ''

            elif buttonId and buttonId.startswith('answer_pollVote_'):
                parts = buttonId.split('_')
                if len(parts) < 6:
                    self.logger.warning(f"⚠️ Invalid vote payload format: {buttonId}")
                    return False
                
                poll_id = parts[2]
                question_index = int(parts[3])
                question_id = parts[4]
                answer = parts[5]

            elif customData and customData.get('action') == 'pollVote':
                poll_id = customData.get('poll_id')
                question_index = customData.get('question_index')
                question_id = customData.get('question_id')
                answer = messageBody

            else:
                return '❌ שגיאה בהצבעה.'
            
            if not question_id:
                self.logger.warning(f"⚠️ Could not find question for answer {answer} in poll {poll_id}")
                return '❌ שגיאה בהצבעה.'
            
            # Get poll to find question_id from answer_id
            poll_data = self.get_poll(pollId=poll_id)
            if not poll_data:
                return '❌ סקר לא נמצא.'
            
            questions = poll_data.get('questions', [])
            
            # Record the vote
            vote_success = self.record_vote(
                poll_id=poll_id,
                question_index=question_index,
                question_id=question_id,
                answer=answer,
                mobileNo=mobileNo,
            )
            
            if not vote_success:
                return '❌ שגיאה בהצבעה. נסה שוב.'
            
            # If auto_send_next_question is enabled and there are more questions, send the next one
            if auto_send_next_question and question_index is not None:
                next_question_index = question_index + 1
                if next_question_index < len(questions):
                    # Send the next question
                    self.logger.info(f"📤 Auto-sending next question {next_question_index + 1} to user {mobileNo}")
                    await self.send_poll(
                        poll_id=poll_id,
                        to=mobileNo,
                        send_all_questions=False,
                        question_index=next_question_index
                    )
                else:
                    # All questions answered - send completion message
                    self.logger.info(f"✅ User {mobileNo} completed all questions in poll {poll_id}")
                    completion_message = f"✅ תודה! סיימת את הסקר '{poll_data.get('title', 'Poll')}'"
                    pwaDocUrl = f'{self.messagingService.docsServiceUrlBase}{quote("התקנת אפליקציית RefereeX.pdf")}'
                    pwaDocFileName = 'התקנת אפליקציית RefereeX'
                    try:
                        #await self.messagingService.sendMessage(to=mobileNo, message=completion_message)
                        self.messagingService.metaClient.sendDocumentMessage(to=mobileNo, filePath=pwaDocUrl, message=completion_message, filename=pwaDocFileName)
                    except Exception as ex:
                        self.logger.warning(f"⚠️ Failed to send completion message: {ex}")
            
            return ''
            
        except Exception as ex:
            self.logger.error(f"❌ Error processing vote from message: {ex}", ex)
            return False
    
    def get_poll_results(self, poll_id: str) -> Optional[Dict[str, Any]]:
        """
        Get results and statistics for a poll
        
        Returns:
            Dictionary with poll results including:
            - poll_info: Basic poll information
            - questions: List of questions with vote counts per answer
            - total_votes: Total number of votes
            - unique_voters: Number of unique voters
        """
        try:
            poll_data = self.get_poll(pollId=poll_id)
            if not poll_data:
                return None
            
            results = {
                'poll_id': poll_id,
                'title': poll_data.get('title'),
                'status': poll_data.get('status'),
                'created': poll_data.get('created'),
                'expires_at': poll_data.get('expires_at'),
                'questions': [],
                'total_votes': 0,
                'unique_voters': set()
            }
            
            # Get votes for each question
            for question in poll_data.get('questions', []):
                question_id = question['question_id']
                question_results = {
                    'question_id': question_id,
                    'question': question['question_text'],
                    'answers': []
                }
                
                # Count votes for each answer
                for answer, answer_id in zip(question['answers'], question['answer_ids']):
                    vote_count = self._count_votes_for_answer(poll_id, question_id, answer_id)
                    question_results['answers'].append({
                        'answer': answer,
                        'answer_id': answer_id,
                        'votes': vote_count
                    })
                    results['total_votes'] += vote_count
                
                results['questions'].append(question_results)
            
            # Count unique voters (this is approximate - gets unique users from vote keys)
            # Note: This requires scanning Redis keys, which may be slow for large polls
            results['unique_voters'] = len(self._get_unique_voters(poll_id))
            
            return results
            
        except Exception as ex:
            self.logger.error(f"❌ Error getting poll results: {ex}", ex)
            return None
    
    def _count_votes_for_answer(self, poll_id: str, question_id: str, answer_id: str) -> int:
        """Count votes for a specific answer"""
        try:
            # Note: This is a simplified implementation
            # For production, you might want to use Redis sets or sorted sets for better performance
            pattern = f"{self.vote_prefix}:{poll_id}:{question_id}:*"
            # This would require Redis SCAN which isn't directly available in cacheService
            # For now, we'll use a different approach: store vote counts separately
            
            # Alternative: Store vote counts in a separate key
            vote_count_key = f"{self.vote_prefix}:count:{poll_id}:{question_id}:{answer_id}"
            count_data = self.cacheService._redis_get(key=vote_count_key)
            return count_data.get('count', 0) if count_data else 0
            
        except Exception as ex:
            self.logger.error(f"❌ Error counting votes: {ex}", ex)
            return 0
    
    def _get_unique_voters(self, poll_id: str) -> set:
        """Get set of unique voter IDs for a poll"""
        try:
            voters_key = f"{self.vote_prefix}:voters:{poll_id}"
            voters_data = self.cacheService._redis_get(key=voters_key)
            if voters_data:
                return set(voters_data.get('voters', []))
            return set()
        except Exception as ex:
            self.logger.error(f"❌ Error getting unique voters: {ex}", ex)
            return set()
    
    def close_poll(self, poll_id: str) -> bool:
        """Close a poll (prevent further voting)"""
        try:
            poll_data = self.get_poll(pollId=poll_id)
            if not poll_data:
                return False
            
            poll_data['status'] = 'closed'
            poll_key = f"{self.poll_prefix}:{poll_id}"
            return self.cacheService._redis_set(
                key=poll_key,
                data=poll_data,
                ttl_seconds=self.default_ttl_seconds
            )
        except Exception as ex:
            self.logger.error(f"❌ Error closing poll: {ex}", ex)
            return False
    
    def delete_poll(self, poll_id: str) -> bool:
        """Delete a poll and all its votes"""
        try:
            poll_key = f"{self.poll_prefix}:{poll_id}"
            return self.cacheService._redis_delete(key=poll_key)
        except Exception as ex:
            self.logger.error(f"❌ Error deleting poll: {ex}", ex)
            return False


if __name__ == "__main__":
    from shared.appContainer import AppContainer
    container = AppContainer.getAppContainer()
    cacheService:CacheService = container.cache_service()
    messagingService:MessagingService = container.messaging_service()

    pwaDocUrl = f'{messagingService.docsServiceUrlBase}{quote("התקנת אפליקציית RefereeX.pdf")}'
    pwaDocFileName = 'התקנת אפליקציית RefereeX'
    messagingService.metaClient.sendDocumentMessage(to='+972547799979', filePath=pwaDocUrl, message=completion_message, filename=pwaDocFileName)

    poll_id = '94c421b8-2cab-43e0-a94b-4c06a96991c0'
    mobileNo = '+972547799979'
    question_id = 'q1'
    existing_vote = cacheService.getPollVotes(pollId=poll_id, mobileNo=mobileNo, questionId=question_id)

    buttons = ["xxxxx","sdsdsdsdsdsd","sdsds"]
    maxButtonTextLength = max([len(button) for button in buttons])
    buttons = ["","",""]
    maxButtonTextLength = max([len(button) for button in buttons])
    pass