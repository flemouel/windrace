<?php
// Enregistrement des résultats du jeu
header('Content-Type: application/json');

$starttime = isset($_GET['starttime']) ? $_GET['starttime'] : 0;
$finishindex = isset($_GET['finishindex']) ? $_GET['finishindex'] : 0;
$finalresult = isset($_GET['finalresult']) ? intval($_GET['finalresult']) : 0;

// Déterminer le badge/achievement basé sur la performance
$achievement = "";
if ($finalresult >= 100) {
    $achievement = "Outstanding!";
} elseif ($finalresult >= 50) {
    $achievement = "Great job!";
} elseif ($finalresult >= 20) {
    $achievement = "Well done!";
}

$response = [
    'id' => rand(100000, 999999), // ID de simulation
    'achievement' => $achievement
];

echo json_encode($response);
?>
