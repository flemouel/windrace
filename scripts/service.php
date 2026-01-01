<?php
// Simulation de service de données de vent
// Ce fichier simule les données de vent en temps réel

header('Content-Type: application/json');

$timestamp = isset($_GET['timestamp']) ? intval($_GET['timestamp']) : time();
$length = isset($_GET['length']) ? intval($_GET['length']) : 600;

// Générer des données de vent simulées
$direction = [];
$speed = [];

// Simulation d'une direction de vent moyenne autour de 45 degrés avec des variations
$base_direction = 45;
$base_speed = 8;

for ($i = 0; $i < $length; $i++) {
    // Ajouter de la variation au vent
    $direction[] = $base_direction + (rand(-15, 15) + sin($i / 10) * 10);
    $speed[] = max(0, $base_speed + (rand(-2, 3) + cos($i / 15) * 2));
}

$response = [
    'timestamp' => $timestamp,
    'direction' => $direction,
    'speed' => $speed
];

echo json_encode($response);
?>
