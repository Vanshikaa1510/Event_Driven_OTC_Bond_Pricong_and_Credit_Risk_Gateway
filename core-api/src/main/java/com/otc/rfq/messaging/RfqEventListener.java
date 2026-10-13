package com.otc.rfq.messaging;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.otc.rfq.domain.RfqStatus;
import com.otc.rfq.service.RfqService;
import java.util.UUID;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class RfqEventListener {
    private static final Logger logger = LoggerFactory.getLogger(RfqEventListener.class);
    private final ObjectMapper objectMapper;
    private final RfqService rfqService;
    private final RfqEventValidator eventValidator;

    public RfqEventListener(ObjectMapper objectMapper, RfqService rfqService, RfqEventValidator eventValidator) {
        this.objectMapper = objectMapper;
        this.rfqService = rfqService;
        this.eventValidator = eventValidator;
    }

    @KafkaListener(topics = "rfq.status", groupId = "rfq-core")
    public void onStatus(ConsumerRecord<String, String> record) throws Exception {
        JsonNode event = objectMapper.readTree(record.value());
        UUID rfqId = eventValidator.validateStatus(event);
        rfqService.applyStatus(rfqId, RfqStatus.valueOf(event.required("status").asText()));
    }

    @KafkaListener(topics = "rfq.processed", groupId = "rfq-core")
    public void onProcessed(ConsumerRecord<String, String> record) throws Exception {
        JsonNode event = objectMapper.readTree(record.value());
        UUID rfqId = eventValidator.validateProcessed(event);
        JsonNode result = event.required("result");
        rfqService.applyResult(rfqId, result);
        logger.info("RFQ {} passed agent proposal to deterministic finance gate", rfqId);
    }
}