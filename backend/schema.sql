-- Create database if not exists
CREATE DATABASE IF NOT EXISTS car_visits_tracker;
USE car_visits_tracker;

-- 1. Users Table (Admin Access)
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Vehicles Table (Owner and vehicle master records)
CREATE TABLE IF NOT EXISTS vehicles (
    plate_number VARCHAR(20) PRIMARY KEY, -- Cleaned uppercase, no spaces
    color VARCHAR(30),
    brand VARCHAR(50),
    owner_name VARCHAR(100),
    owner_phone VARCHAR(20),
    owner_email VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 3. Visits Table (Tracks entries and exits)
CREATE TABLE IF NOT EXISTS visits (
    id INT AUTO_INCREMENT PRIMARY KEY,
    plate_number VARCHAR(20) NOT NULL,
    zone VARCHAR(10) NOT NULL, -- 'Zone A' or 'Zone B'
    entry_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    exit_timestamp TIMESTAMP NULL,
    entry_image_url VARCHAR(255),
    exit_image_url VARCHAR(255),
    status VARCHAR(20) DEFAULT 'Inside', -- 'Inside', 'Completed'
    manually_created BOOLEAN DEFAULT FALSE,
    manually_edited BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (plate_number) REFERENCES vehicles(plate_number) ON UPDATE CASCADE
);
