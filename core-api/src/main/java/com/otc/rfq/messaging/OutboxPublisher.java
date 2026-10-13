package com.otc.rfq.messaging;

import com.otc.rfq.domain.OutboxEvent;
import com.otc.rfq.repository.OutboxRepository;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
public class OutboxPublisher {
    private static final Logger logger = LoggerFactory.getLogger(OutboxPublisher.class);
    private final OutboxRepository outboxRepository;
    private final KafkaTemplate<String, String> kafkaTemplate;

    public OutboxPublisher(OutboxRepository outboxRepository, KafkaTemplate<String, String> kafkaTemplate) {
        this.outboxRepository = outboxRepository;
        this.kafkaTemplate = kafkaTemplate;
    }

    @Scheduled(fixedDelayString = "${rfq.outbox.poll-ms:250}")
    @Transactional
    public void publishPending() {
        for (OutboxEvent event : outboxRepository.lockPending(PageRequest.of(0, 100))) {
            try {
                kafkaTemplate.send(event.getEventType(), event.getAggregateId().toString(), event.getPayload())
                        .get(5, TimeUnit.SECONDS);
                event.markPublished();
            } catch (Exception exception) {
                logger.warn("Outbox publish failed for RFQ {}: {}", event.getAggregateId(), exception.toString());
                throw new IllegalStateException("Outbox publish failed; transaction will retry", exception);
            }
        }
    }
}