FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY pom.xml .
COPY src ./src
RUN mvn -q -DskipTests package

FROM eclipse-temurin:21-jre
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /build/target/rfq-core-0.1.0.jar /app/rfq-core.jar
EXPOSE 8080
CMD ["java", "-XX:MaxRAMPercentage=75", "-jar", "/app/rfq-core.jar"]